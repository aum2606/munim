import hmac
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.guardrails import GuardrailViolation, check_prices
from app.channels.whatsapp import WhatsAppAdapter, WhatsAppGraph
from app.core.config import Settings
from app.core.credentials import decrypt_credential, encrypt_credential
from app.core.errors import DomainError, NotFound
from app.core.tenant import TenantContext
from app.db.models import ChannelAccount, Conversation, WhatsAppTemplate
from app.db.models.channel import AccountStatus
from app.repositories.channels import ChannelDiscovery, ChannelRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.whatsapp import ConnectWhatsApp, MetaWebhook
from app.workers.queue import JobQueue


def usable_template(value: dict[str, Any]) -> tuple[str, bool]:
    components = value.get("components", [])
    if (
        not isinstance(components, list)
        or len(components) != 1
        or not isinstance(components[0], dict)
    ):
        return "", False
    component = components[0]
    body = component.get("text", "")
    if (
        not isinstance(body, str)
        or component.get("type") != "BODY"
        or not body.strip()
        or len(body) > 4000
    ):
        return "", False
    usable = value.get("status") == "APPROVED" and "{{" not in body and "}}" not in body
    try:
        check_prices(body, set())
    except GuardrailViolation:
        usable = False
    return body, usable


async def require_send(
    session: AsyncSession,
    ctx: TenantContext,
    config: Settings,
    conversation_id: UUID,
    template_id: UUID | None = None,
) -> WhatsAppTemplate | None:
    conversation = await ScopedRepository(session, ctx, Conversation).get(conversation_id)
    if conversation.channel == "web":
        return None
    repository = ChannelRepository(session, ctx)
    contact = await repository.contact(conversation_id)
    account = await repository.get(contact.account_id)
    if account.status != AccountStatus.ACTIVE or contact.opted_out:
        raise DomainError("WhatsApp account disabled or customer opted out", 409)
    if template_id:
        template = await ScopedRepository(session, ctx, WhatsAppTemplate).get(template_id)
        if template.account_id != account.id:
            raise NotFound()
        if not template.usable or template.status != "APPROVED" or contact.opted_in_at is None:
            raise DomainError(
                "An approved static template and recorded customer opt-in are required", 409
            )
        return template
    if not WhatsAppAdapter(config).can_send_freeform(conversation):
        raise DomainError(
            "The WhatsApp reply window closed. "
            "Send an approved template or wait for a customer reply.",
            409,
        )
    return None


class WhatsAppService:
    def __init__(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        config: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.session, self.ctx, self.config, self.transport = session, ctx, config, transport
        self.repository = ChannelRepository(session, ctx)

    def graph(self, account: ChannelAccount) -> WhatsAppGraph:
        return WhatsAppGraph(
            self.config,
            decrypt_credential(
                self.config.credentials_encryption_key, account.credentials_encrypted
            ),
            self.transport,
        )

    async def connect(self, body: ConnectWhatsApp) -> ChannelAccount:
        encrypted = encrypt_credential(self.config.credentials_encryption_key, body.access_token)
        graph = WhatsAppGraph(self.config, body.access_token.get_secret_value(), self.transport)
        await graph.verify_account(body.phone_number_id, body.business_account_id)
        try:
            existing = await self.repository.by_phone(body.phone_number_id)
        except NotFound:
            try:
                existing = await self.repository.create(
                    external_id=body.phone_number_id,
                    business_account_id=body.business_account_id,
                    credentials_encrypted=encrypted,
                )
            except IntegrityError as error:
                await self.session.rollback()
                raise DomainError(
                    "This phone number is already connected to another workspace", 409
                ) from error
        else:
            if existing.business_account_id != body.business_account_id:
                raise DomainError("Reconnect using the original business account", 409)
            existing.credentials_encrypted, existing.status = encrypted, AccountStatus.ACTIVE
        await self.session.commit()
        return existing

    async def sync_templates(self, account_id: UUID) -> list[WhatsAppTemplate]:
        account = await self.repository.get(account_id)
        values = await self.graph(account).list_resources(
            account.business_account_id + "/message_templates", "id,name,language,status,components"
        )
        existing = {
            (entry.name, entry.language): entry
            for entry in await self.repository.templates(account_id)
        }
        for previous in existing.values():
            previous.usable = False
            previous.status = "UNAVAILABLE"
        for value in values:
            name, language, provider_id, status = (
                value.get(key) for key in ("name", "language", "id", "status")
            )
            if not all(
                isinstance(entry, str) and 0 < len(entry) <= 256
                for entry in [name, language, provider_id, status]
            ):
                raise DomainError("Invalid Meta template registry entry", 502)
            # Provider strings remain untrusted metadata.
            name, language, provider_id, status = (
                str(name),
                str(language),
                str(provider_id),
                str(status),
            )
            text, usable = usable_template(value)
            template = existing.get((name, language))
            if template is None:
                template = await ScopedRepository(self.session, self.ctx, WhatsAppTemplate).create(
                    account_id=account.id,
                    name=name,
                    language=language,
                    provider_id=provider_id,
                    status=status,
                    body_text=text,
                    usable=usable,
                )
            else:
                template.provider_id, template.status, template.body_text, template.usable = (
                    provider_id,
                    status,
                    text,
                    usable,
                )
        await self.session.commit()
        return await self.repository.templates(account_id)


async def ingest_webhook(
    session: AsyncSession, config: Settings, queue: JobQueue, raw: bytes, signature: str
) -> None:
    if not config.whatsapp_app_secret.get_secret_value():
        raise DomainError("WhatsApp webhook is not configured", 503)
    adapter = WhatsAppAdapter(config)
    if not adapter.verify_webhook(raw, signature):
        raise DomainError("Invalid webhook signature", 403)
    try:
        payload = MetaWebhook.model_validate_json(raw)
    except ValueError as error:
        raise DomainError("Invalid WhatsApp webhook", 400) from error
    jobs: list[tuple[UUID, UUID]] = []
    count = 0
    for entry in payload.entry:
        for change in entry.changes:
            if change.field != "messages" or not change.value.metadata:
                continue
            count += len(change.value.messages) + len(change.value.statuses)
            if count > 100:
                raise DomainError("Webhook batch exceeds supported size", 413)
            phone_id = change.value.metadata.phone_number_id
            ctx = await ChannelDiscovery(session).tenant(phone_id, entry.id)
            if ctx is None:
                continue
            repository = ChannelRepository(session, ctx)
            account = await repository.by_phone(phone_id)
            if account.status != AccountStatus.ACTIVE:
                continue
            for message in change.value.messages:
                inbound = adapter.parse_inbound(message)
                saved = await repository.inbound(
                    account,
                    inbound.wa_id,
                    inbound.provider_id,
                    inbound.content,
                    inbound.timestamp,
                    inbound.content_type,
                    inbound.attachments,
                )
                if saved.processed_at is None:
                    jobs.append((ctx.tenant_id, saved.id))
            for status in change.value.statuses:
                await repository.status(account.id, status.id, status.status)
    await session.commit()
    # A failed enqueue returns 503, causing provider replay. Durable message IDs deduplicate it.
    for tenant_id, message_id in jobs:
        await queue.enqueue("process_message", tenant_id, message_id)


def verify_challenge(config: Settings, mode: str, token: str, challenge: str) -> str:
    expected = config.whatsapp_verify_token.get_secret_value()
    if not expected:
        raise DomainError("WhatsApp webhook is not configured", 503)
    if mode != "subscribe" or not hmac.compare_digest(expected.encode(), token.encode()):
        raise DomainError("Invalid webhook verification token", 403)
    return challenge
