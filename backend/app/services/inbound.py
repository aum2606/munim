"""Turning WhatsApp webhook events into stored messages and jobs."""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import InboundMessage, StatusUpdate
from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import ConversationMode, Direction, SenderType
from app.jobs.queue import enqueue
from app.orchestrator.messages import canned
from app.repositories.channels import tenant_for_phone_number_id
from app.repositories.chat import ChatRepository

log = structlog.get_logger()

_VOICE_PLACEHOLDER = "[voice note]"
_UNSUPPORTED_PLACEHOLDER = "[unsupported message]"


class InboundService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._tenants: dict[str, uuid.UUID | None] = {}

    async def receive(self, messages: list[InboundMessage], statuses: list[StatusUpdate]) -> None:
        for message in messages:
            if ctx := await self._context(message.phone_number_id):
                await self._message(ctx, message)
        for status in statuses:
            if ctx := await self._context(status.phone_number_id):
                await ChatRepository(self._session, ctx).set_delivery_by_external_id(
                    status.external_id, status.status, status.error
                )

    async def _context(self, phone_number_id: str) -> TenantContext | None:
        if phone_number_id not in self._tenants:
            self._tenants[phone_number_id] = await tenant_for_phone_number_id(
                self._session, phone_number_id
            )
        tenant_id = self._tenants[phone_number_id]
        if tenant_id is None:
            log.warning("whatsapp_unknown_number")  # a number nobody here has connected
            return None
        return TenantContext.system(tenant_id)

    async def _message(self, ctx: TenantContext, inbound: InboundMessage) -> None:
        chat = ChatRepository(self._session, ctx)
        conversation = await chat.whatsapp_conversation(inbound.sender_phone, inbound.sender_name)
        is_voice = inbound.kind == "audio" and inbound.media_id is not None
        stored = await chat.add_inbound_once(
            conversation,
            external_id=inbound.external_id,
            content=inbound.text
            if inbound.kind == "text"
            else (_VOICE_PLACEHOLDER if is_voice else _UNSUPPORTED_PLACEHOLDER),
            kind="audio" if is_voice else inbound.kind,
            media_id=inbound.media_id if is_voice else None,
        )
        if stored is None:
            return  # already seen: Meta retries webhooks
        since = datetime.now(UTC) - timedelta(minutes=10)
        if await chat.count_inbound_since(conversation.id, since) > (
            self._settings.customer_messages_per_10_min
        ):
            # Kept for the owner to read, but no model call and no reply: one chat must not use
            # up the model quota that every other customer shares.
            log.warning("customer_message_flood")
            await chat.mark_handled([stored.id])
            return

        if is_voice:
            await enqueue(self._session, ctx, "transcribe_message", {"message_id": str(stored.id)})
        elif inbound.kind == "text":
            due = datetime.now(UTC) + timedelta(seconds=self._settings.debounce_seconds)
            await enqueue(
                self._session,
                ctx,
                "process_message",
                {"conversation_id": str(conversation.id)},
                run_at=due,
            )
        else:
            await chat.mark_handled([stored.id])
            if conversation.mode == ConversationMode.AI:
                language = await chat.last_language(conversation.id) or "en"
                await chat.add_message(
                    conversation,
                    direction=Direction.OUT,
                    sender_type=SenderType.AI,
                    content=canned("unsupported", language),
                    language=language,
                    reply_to_id=stored.id,
                )
