from datetime import UTC, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.guardrails import check_reply
from app.agents.handoff import HandoffAgent
from app.analytics.events import emit
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models import Handoff, Message, ReplyDraft
from app.db.models.analytics import AnalyticsEventType as Event
from app.db.models.conversation import ConversationMode, ConversationStatus, Direction, SenderType
from app.llm import LLMClient
from app.orchestrator.localized import fallback
from app.repositories.conversations import ConversationRepository
from app.repositories.identity import TenantRepository
from app.repositories.inbox import InboxRepository
from app.repositories.leads import LeadRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.leads import HandoffInput
from app.tools.inbox_prices import reply_prices


def holding_message(language: str, closed: bool) -> str:
    suffixes = {
        "en": " The team will review this during business hours.",
        "hinglish": " Team business hours mein isse dekhegi.",
        "gujlish": " Team business hours ma aa joshe.",
        "hi": " टीम काम के समय इसकी समीक्षा करेगी।",
        "gu": " ટીમ કામકાજના સમયમાં આ તપાસશે.",
    }
    return fallback(language) + (suffixes.get(language, suffixes["en"]) if closed else "")


def outside_hours(hours: dict[str, object], timezone: str, now: datetime) -> bool:
    if not hours:
        return False
    local = now.astimezone(ZoneInfo(timezone))
    # Owner configuration: weekday names -> [HH:MM, HH:MM]; absent/empty days are closed.
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    current = local.time().replace(tzinfo=None)
    for offset in (0, 1):
        window = hours.get(days[(local.weekday() - offset) % 7])
        if not isinstance(window, list) or len(window) != 2:
            continue
        try:
            start, end = time.fromisoformat(str(window[0])), time.fromisoformat(str(window[1]))
        except ValueError:
            continue
        if start.tzinfo or end.tzinfo:
            continue
        if offset == 0 and (start <= current < end if start <= end else current >= start):
            return False
        if offset == 1 and start > end and current < end:
            return False
    return True


class InboxService:
    def __init__(self, session: AsyncSession, ctx: TenantContext, config: Settings) -> None:
        self.session, self.ctx, self.config = session, ctx, config
        self.repository = InboxRepository(session, ctx)
        self.conversations = ConversationRepository(session, ctx)

    async def handoff(
        self, conversation_id: UUID, message_id: UUID, reason: str, language: str, llm: LLMClient
    ) -> str | None:
        conversation = await self.conversations.get(conversation_id, for_update=True)
        if (
            conversation.mode == ConversationMode.HUMAN
            or conversation.status != ConversationStatus.OPEN
        ):
            return None
        history = await self.conversations.messages(conversation_id, 8)
        summary = "Staff assistance required: " + reason
        try:
            result = await HandoffAgent(llm).run(
                self.ctx,
                HandoffInput(reason=reason, messages=[message.content for message in history]),
                message_id=message_id,
            )
            summary = result.summary
        except (
            ValidationError,
            ValueError,
            httpx.HTTPError,
            PermissionError,
            DomainError,
        ) as error:
            # A failed summarizer must never prevent the deterministic safety handoff.
            structlog.get_logger().warning("handoff_summary_failed", error=type(error).__name__)
        if not await self.repository.handoffs(conversation_id):
            handoff = await ScopedRepository(self.session, self.ctx, Handoff).create(
                conversation_id=conversation_id,
                reason=reason,
                summary=summary,
            )
            await emit(
                self.session, self.ctx, Event.HANDOFF, handoff.id, conversation_id=conversation_id
            )
        tenant = await TenantRepository(self.session, self.ctx).get()
        settings = await TenantRepository(self.session, self.ctx).settings()
        text = holding_message(
            language, outside_hours(settings.business_hours, tenant.timezone, datetime.now(UTC))
        )
        check_reply(text, set(), [text])
        return text

    async def mode(self, conversation_id: UUID, mode: ConversationMode) -> None:
        conversation = await self.conversations.get(conversation_id, for_update=True)
        if conversation.mode != mode:
            await self.repository.resolve(conversation_id)
            conversation.mode = mode
            if mode != ConversationMode.AI:
                handoff = await ScopedRepository(self.session, self.ctx, Handoff).create(
                    conversation_id=conversation_id,
                    reason="staff_takeover",
                    summary="Staff changed conversation mode.",
                )
                await emit(
                    self.session,
                    self.ctx,
                    Event.HANDOFF,
                    handoff.id,
                    conversation_id=conversation_id,
                )
        # Takeover and return consume all earlier inbound; old jobs cannot answer them later.
        for message in await self.conversations.pending(conversation_id):
            message.processed_at = datetime.now(UTC)
        await self.session.commit()

    async def reply(
        self,
        conversation_id: UUID,
        content: str,
        external_id: str,
        buttons: list[dict[str, str]] | None = None,
    ) -> Message:
        conversation = await self.conversations.get(conversation_id, for_update=True)
        existing = await self.repository.outbound(conversation_id, "staff:" + external_id)
        if existing:
            existing_buttons: object = next(
                (entry.get("buttons") for entry in existing.attachments if entry.get("buttons")), []
            )
            if existing.content != content or existing_buttons != (buttons or []):
                raise DomainError("Message ID already used for different content", 409)
            return existing
        if (
            conversation.mode == ConversationMode.AI
            or conversation.status != ConversationStatus.OPEN
        ):
            raise DomainError("Take over this open conversation before replying", 409)
        from app.channels.service import require_send

        await require_send(self.session, self.ctx, self.config, conversation_id)
        settings = await TenantRepository(self.session, self.ctx).settings()
        allowed = await reply_prices(self.session, self.ctx, self.config, conversation_id)
        check_reply(content, allowed, [content], settings.max_auto_discount_pct)
        if buttons:
            from app.agents.guardrails import check_prices

            if conversation.channel != "whatsapp":
                raise DomainError("Reply buttons are available on WhatsApp", 409)
            for button in buttons:
                check_prices(button["title"], set())
        message = await ScopedRepository(self.session, self.ctx, Message).create(
            conversation_id=conversation_id,
            direction=Direction.OUT,
            sender_type=SenderType.STAFF,
            content=content,
            external_id="staff:" + external_id,
            attachments=[{"buttons": buttons}] if buttons else [],
        )
        conversation.last_business_msg_at = datetime.now(UTC)
        for draft in await self.repository.drafts(conversation_id):
            draft.status = "discarded"
        await self.session.flush()
        from app.repositories.channels import ChannelRepository

        await ChannelRepository(self.session, self.ctx).queue(message)
        await emit(
            self.session, self.ctx, Event.STAFF_REPLY, message.id, conversation_id=conversation_id
        )
        return message

    async def approve_draft(self, draft_id: UUID) -> Message:
        initial = await self.repository.draft(draft_id)
        conversation = await self.conversations.get(initial.conversation_id, for_update=True)
        draft = await ScopedRepository(self.session, self.ctx, ReplyDraft).get(
            draft_id, for_update=True
        )
        existing = await self.repository.outbound(conversation.id, "staff:draft:" + str(draft.id))
        if existing:
            return existing
        latest = await LeadRepository(self.session, self.ctx).latest_inbound(conversation.id)
        if (
            conversation.mode != ConversationMode.ASSIST
            or draft.status != "pending"
            or not latest
            or latest.id != draft.source_message_id
        ):
            raise DomainError("Draft is stale; review the latest conversation", 409)
        message = await self.reply(conversation.id, draft.content, "draft:" + str(draft.id))
        draft.status = "sent"
        await self.session.commit()
        return message
