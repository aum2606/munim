import hmac
from datetime import UTC, datetime
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
from app.schemas.whatsapp import (
    ConnectWhatsApp,
    ConsentChange,
    ConsentView,
    DeliveryResolution,
    DeliveryView,
    FollowupOptions,
    MetaWebhook,
    SetupView,
    TemplateView,
)
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
    from app.db.models.conversation import ConversationStatus

    if conversation.status != ConversationStatus.OPEN:
        raise DomainError("Reopen the conversation before sending", 409)
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

    async def media(
        self, conversation_id: UUID, message_id: UUID, media_id: str
    ) -> tuple[bytes, str]:
        from app.db.models import Message

        await ScopedRepository(self.session, self.ctx, Conversation).get(conversation_id)
        message = await ScopedRepository(self.session, self.ctx, Message).get(message_id)
        if message.conversation_id != conversation_id:
            raise NotFound()
        attachment = next(
            (entry for entry in message.attachments if entry.get("media_id") == media_id), None
        )
        if attachment is None:
            raise NotFound()
        contact = await self.repository.contact(conversation_id)
        account = await self.repository.get(contact.account_id)
        content = await self.graph(account).download_media(account.external_id, media_id)
        filename = attachment.get("filename")
        import re

        safe = re.sub(r"[^A-Za-z0-9 ._-]", "", str(filename or "attachment"))[:100] or "attachment"
        return content, safe

    def setup_view(self) -> SetupView:
        import re

        from app.core.credentials import cipher

        encryption_ready = True
        try:
            cipher(self.config.credentials_encryption_key)
        except DomainError:
            encryption_ready = False
        return SetupView(
            callback_url=self.config.public_api_url.rstrip("/") + "/api/v1/webhooks/whatsapp",
            encryption_ready=encryption_ready,
            webhook_ready=bool(
                self.config.whatsapp_app_secret.get_secret_value()
                and self.config.whatsapp_verify_token.get_secret_value()
            ),
            api_version_ready=bool(re.fullmatch(r"v[0-9]+\.0", self.config.whatsapp_api_version)),
        )

    async def consent_view(self, conversation_id: UUID) -> ConsentView:
        conversation = await ScopedRepository(self.session, self.ctx, Conversation).get(
            conversation_id
        )
        contact = await self.repository.contact(conversation_id)
        account = await self.repository.get(contact.account_id)
        return ConsentView.model_validate(contact).model_copy(
            update={
                "freeform_allowed": account.status == AccountStatus.ACTIVE
                and not contact.opted_out
                and WhatsAppAdapter(self.config).can_send_freeform(conversation)
            }
        )

    async def record_consent(self, conversation_id: UUID, body: ConsentChange) -> ConsentView:
        await ScopedRepository(self.session, self.ctx, Conversation).get(
            conversation_id, for_update=True
        )
        contact = await self.repository.contact(conversation_id)
        contact.opted_in_at = datetime.now(UTC) if body.opted_in else None
        contact.opted_out, contact.consent_note, contact.consent_by = (
            not body.opted_in,
            body.note,
            self.ctx.user_id,
        )
        await self.session.commit()
        return await self.consent_view(conversation_id)

    async def change_account(self, account_id: UUID, status: AccountStatus) -> ChannelAccount:
        account = await self.repository.get(account_id, for_update=True)
        account.status = status
        await self.session.commit()
        return account

    async def delivery_views(self) -> list[DeliveryView]:
        from app.db.models import Message

        views = []
        for delivery in await self.repository.deliveries():
            message = await ScopedRepository(self.session, self.ctx, Message).get(
                delivery.message_id
            )
            views.append(
                DeliveryView.model_validate(delivery).model_copy(
                    update={
                        "conversation_id": message.conversation_id,
                        "content_preview": message.content[:200],
                    }
                )
            )
        return views

    async def followup_options(self, followup_id: UUID) -> FollowupOptions:
        from app.db.models import Followup
        from app.repositories.leads import LeadRepository

        draft = await ScopedRepository(self.session, self.ctx, Followup).get(followup_id)
        lead = await LeadRepository(self.session, self.ctx).get(draft.lead_id)
        contact = await self.repository.contact(lead.conversation_id)
        templates = await self.repository.templates(contact.account_id)
        return FollowupOptions(
            conversation_id=lead.conversation_id,
            consent=ConsentView.model_validate(contact),
            templates=[
                TemplateView.model_validate(template) for template in templates if template.usable
            ],
        )

    async def resolve(self, delivery_id: UUID, body: DeliveryResolution) -> DeliveryView:
        import structlog

        from app.db.models import ChannelDelivery
        from app.db.models.channel import DeliveryStatus

        delivery = await ScopedRepository(self.session, self.ctx, ChannelDelivery).get(
            delivery_id, for_update=True
        )
        if delivery.status not in {
            DeliveryStatus.UNCERTAIN,
            DeliveryStatus.FAILED,
            DeliveryStatus.BLOCKED,
        }:
            raise DomainError("Only a delivery needing attention can be reconciled", 409)
        if body.provider_message_id and body.confirmed_not_sent:
            raise DomainError(
                "Choose either a confirmed provider ID or confirmation it was not sent"
            )
        if body.provider_message_id:
            delivery.provider_message_id, delivery.status = (
                body.provider_message_id,
                DeliveryStatus.SENT,
            )
            await self.repository.reconcile(delivery)
        elif body.confirmed_not_sent:
            delivery.status, delivery.attempts = DeliveryStatus.QUEUED, 0
            delivery.next_attempt_at = datetime.now(UTC)
        else:
            raise DomainError("Confirm the delivery outcome before retrying", 409)
        delivery.last_error = "owner_reconciled:" + str(self.ctx.user_id)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise DomainError(
                "Provider message ID is already assigned to another delivery", 409
            ) from error
        structlog.get_logger().info(
            "whatsapp_owner_reconciled",
            tenant_id=str(self.ctx.tenant_id),
            delivery_id=str(delivery_id),
            actor=str(self.ctx.user_id),
        )
        return DeliveryView.model_validate(delivery)

    async def connect(self, body: ConnectWhatsApp) -> ChannelAccount:
        encrypted = encrypt_credential(self.config.credentials_encryption_key, body.access_token)
        graph = WhatsAppGraph(self.config, body.access_token.get_secret_value(), self.transport)
        await graph.verify_account(body.phone_number_id, body.business_account_id)
        # Official subscription contract: https://www.postman.com/meta/whatsapp-business-platform/request/c1ai24q/subscribe-to-your-waba
        subscribed = await graph.request("POST", body.business_account_id + "/subscribed_apps")
        if subscribed.get("success") not in (True, "true"):
            raise DomainError("Meta did not confirm the webhook subscription", 502)
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
            if account.status == AccountStatus.ACTIVE:
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
