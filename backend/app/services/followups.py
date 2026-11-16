"""Follow-up drafts: a deterministic nudge for a quote nobody answered. The owner decides whether
it goes out; nothing here is sent automatically, and no model writes it."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp import window_open
from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import ConflictError, NotFoundError
from app.db.models import Channel, FollowUp, FollowUpStatus
from app.orchestrator.messages import canned
from app.repositories.chat import ChatRepository
from app.repositories.followups import FollowUpRepository
from app.schemas.followups import FollowUpOut
from app.services.conversations import ConversationService


class FollowUpService:
    def __init__(self, session: AsyncSession, ctx: TenantContext, settings: Settings) -> None:
        self._session = session
        self._ctx = ctx
        self._settings = settings
        self._repo = FollowUpRepository(session, ctx)
        self._chat = ChatRepository(session, ctx)

    async def generate(self) -> int:
        """Draft a nudge for every quote that has sat unanswered long enough. Returns how many."""
        cutoff = datetime.now(UTC) - timedelta(days=self._settings.followup_after_days)
        created = 0
        for quote, conversation_id in await self._repo.unanswered_quotes(cutoff):
            language = await self._chat.last_language(conversation_id) or "en"
            draft = canned("followup", language).format(number=quote.quote_number)
            await self._repo.add(conversation_id, quote.id, draft)
            created += 1
        return created

    async def listing(self, status: FollowUpStatus | None) -> list[FollowUpOut]:
        now = datetime.now(UTC)
        out: list[FollowUpOut] = []
        for follow_up, number in await self._repo.browse(status):
            conversation = await self._chat.get_conversation(follow_up.conversation_id)
            customer = (
                await self._chat.get_customer(conversation.customer_id) if conversation else None
            )
            item = FollowUpOut.model_validate(follow_up)
            item.quote_number = number
            item.customer_name = customer.name if customer else None
            item.can_send = conversation is not None and (
                conversation.channel != Channel.WHATSAPP
                or window_open(conversation.last_customer_msg_at, now)
            )
            out.append(item)
        return out

    async def send(self, follow_up_id: uuid.UUID, text: str | None) -> FollowUp:
        follow_up = await self._draft(follow_up_id)
        # Goes through the normal staff reply, which refuses when WhatsApp's 24-hour window is shut.
        await ConversationService(self._session, self._ctx).staff_reply(
            follow_up.conversation_id, text or follow_up.draft
        )
        follow_up.status = FollowUpStatus.SENT
        return follow_up

    async def dismiss(self, follow_up_id: uuid.UUID) -> FollowUp:
        follow_up = await self._draft(follow_up_id)
        follow_up.status = FollowUpStatus.DISMISSED
        return follow_up

    async def _draft(self, follow_up_id: uuid.UUID) -> FollowUp:
        follow_up = await self._repo.get(follow_up_id)
        if follow_up is None:
            raise NotFoundError("Follow-up not found")
        if follow_up.status != FollowUpStatus.DRAFT:
            raise ConflictError("This follow-up has already been handled")
        return follow_up
