from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models.lead import Lead
from app.repositories.conversations import ConversationRepository
from app.repositories.scoped import ScopedRepository


class LeadRepository(ScopedRepository[Lead]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, Lead)

    async def for_conversation(self, conversation_id: UUID, category: str) -> Lead:
        conversation = await ConversationRepository(self.session, self.ctx).get(
            conversation_id, for_update=True
        )
        lead = (
            await self.session.scalars(
                select(Lead).where(
                    Lead.tenant_id == self.ctx.tenant_id,
                    Lead.conversation_id == conversation_id,
                )
            )
        ).one_or_none()
        if lead is None:
            lead = await self.create(
                customer_id=conversation.customer_id,
                conversation_id=conversation_id,
                category=category,
                source_channel=conversation.channel,
            )
        return lead
