import uuid
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import (
    Conversation,
    FollowUp,
    FollowUpStatus,
    Lead,
    Quote,
    QuoteStatus,
)


class FollowUpRepository:
    """Suggested nudges for quotes the customer has not answered. Tenant-scoped."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    async def unanswered_quotes(self, sent_before: datetime) -> list[tuple[Quote, uuid.UUID]]:
        """Sent quotes older than the cutoff that have no follow-up yet and that the customer has
        not written to since. Returns each quote with its conversation id."""
        rows = await self._session.execute(
            select(Quote, Lead.conversation_id)
            .join(Lead, Lead.id == Quote.lead_id)
            .join(Conversation, Conversation.id == Lead.conversation_id)
            .where(
                Quote.tenant_id == self._ctx.tenant_id,
                Quote.status == QuoteStatus.SENT,
                Quote.sent_at <= sent_before,
                Conversation.last_customer_msg_at <= Quote.sent_at,
                ~exists().where(FollowUp.quote_id == Quote.id),
            )
        )
        return [(quote, conversation_id) for quote, conversation_id in rows]

    async def add(self, conversation_id: uuid.UUID, quote_id: uuid.UUID, draft: str) -> FollowUp:
        follow_up = FollowUp(
            tenant_id=self._ctx.tenant_id,
            conversation_id=conversation_id,
            quote_id=quote_id,
            draft=draft,
        )
        self._session.add(follow_up)
        await self._session.flush()
        return follow_up

    async def get(self, follow_up_id: uuid.UUID) -> FollowUp | None:
        return await self._session.scalar(
            select(FollowUp).where(
                FollowUp.tenant_id == self._ctx.tenant_id, FollowUp.id == follow_up_id
            )
        )

    async def browse(self, status: FollowUpStatus | None) -> list[tuple[FollowUp, str]]:
        """Follow-ups with their quote number, newest first."""
        query = (
            select(FollowUp, Quote.quote_number)
            .join(Quote, Quote.id == FollowUp.quote_id)
            .where(FollowUp.tenant_id == self._ctx.tenant_id)
            .order_by(FollowUp.created_at.desc())
            .limit(100)
        )
        if status:
            query = query.where(FollowUp.status == status)
        return [(f, number) for f, number in await self._session.execute(query)]
