from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import Handoff, Message, ReplyDraft
from app.repositories.scoped import ScopedRepository


class InboxRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def handoffs(self, conversation_id: UUID | None = None) -> list[Handoff]:
        statement = select(Handoff).where(
            Handoff.tenant_id == self.ctx.tenant_id, Handoff.status == "open"
        )
        if conversation_id:
            statement = statement.where(Handoff.conversation_id == conversation_id)
        return list(await self.session.scalars(statement.order_by(Handoff.created_at).limit(200)))

    async def drafts(self, conversation_id: UUID) -> list[ReplyDraft]:
        return list(
            await self.session.scalars(
                select(ReplyDraft)
                .where(
                    ReplyDraft.tenant_id == self.ctx.tenant_id,
                    ReplyDraft.conversation_id == conversation_id,
                    ReplyDraft.status == "pending",
                )
                .order_by(ReplyDraft.created_at)
                .limit(100)
            )
        )

    async def outbound(self, conversation_id: UUID, external_id: str) -> Message | None:
        return (
            await self.session.scalars(
                select(Message).where(
                    Message.tenant_id == self.ctx.tenant_id,
                    Message.conversation_id == conversation_id,
                    Message.external_id == external_id,
                )
            )
        ).one_or_none()

    async def resolve(self, conversation_id: UUID) -> None:
        for handoff in await self.handoffs(conversation_id):
            handoff.status, handoff.resolved_by = "resolved", self.ctx.user_id
        for draft in await self.drafts(conversation_id):
            draft.status = "discarded"

    async def draft(self, draft_id: UUID) -> ReplyDraft:
        return await ScopedRepository(self.session, self.ctx, ReplyDraft).get(draft_id)
