import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import (
    AgentRun,
    Conversation,
    Customer,
    KnowledgeGap,
    Lead,
    Message,
    Quote,
)


@dataclass(frozen=True)
class Erased:
    conversations: int
    messages: int
    quotes: int
    pdf_paths: list[str]  # files to remove from storage: the database cannot do that


class CustomerRepository:
    """Customers and everything personal that hangs off them. Tenant-scoped."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    def _mine(
        self, model: type[Customer] | type[Conversation] | type[Message]
    ) -> ColumnElement[bool]:
        return model.tenant_id == self._ctx.tenant_id

    async def browse(self, search: str | None, limit: int = 50) -> list[Customer]:
        query = select(Customer).where(self._mine(Customer))
        if search:
            like = f"%{search.strip()[:60]}%"
            query = query.where(or_(Customer.phone.ilike(like), Customer.name.ilike(like)))
        result = await self._session.scalars(
            query.order_by(Customer.created_at.desc()).limit(limit)
        )
        return list(result)

    async def get(self, customer_id: uuid.UUID) -> Customer | None:
        return await self._session.scalar(
            select(Customer).where(self._mine(Customer), Customer.id == customer_id)
        )

    async def conversations(self, customer_id: uuid.UUID) -> list[Conversation]:
        result = await self._session.scalars(
            select(Conversation)
            .where(self._mine(Conversation), Conversation.customer_id == customer_id)
            .order_by(Conversation.created_at)
        )
        return list(result)

    async def messages(self, conversation_ids: list[uuid.UUID]) -> list[Message]:
        result = await self._session.scalars(
            select(Message)
            .where(self._mine(Message), Message.conversation_id.in_(conversation_ids))
            .order_by(Message.created_at, Message.id)
        )
        return list(result)

    async def quotes(self, customer_id: uuid.UUID) -> list[Quote]:
        result = await self._session.scalars(
            select(Quote)
            .join(Lead, Lead.id == Quote.lead_id)
            .where(Quote.tenant_id == self._ctx.tenant_id, Lead.customer_id == customer_id)
            .order_by(Quote.created_at)
        )
        return list(result)

    async def erase(self, customer_id: uuid.UUID) -> Erased:
        """Delete the customer and every trace of what they said.

        The database cascades conversations, messages, leads, quotes, quote lines and follow-ups.
        It does NOT reach `agent_runs` (their input and output hold the customer's words; the link
        to the message is only nulled) or the knowledge gap that quotes them, so those go first.
        """
        conversations = [c.id for c in await self.conversations(customer_id)]
        messages = [m.id for m in await self.messages(conversations)] if conversations else []
        quotes = await self.quotes(customer_id)
        if messages:
            await self._session.execute(
                delete(AgentRun).where(
                    AgentRun.tenant_id == self._ctx.tenant_id, AgentRun.message_id.in_(messages)
                )
            )
            await self._session.execute(
                delete(KnowledgeGap).where(
                    KnowledgeGap.tenant_id == self._ctx.tenant_id,
                    KnowledgeGap.example_message_id.in_(messages),
                )
            )
        await self._session.execute(
            delete(Customer).where(self._mine(Customer), Customer.id == customer_id)
        )
        return Erased(
            conversations=len(conversations),
            messages=len(messages),
            quotes=len(quotes),
            pdf_paths=[q.pdf_path for q in quotes if q.pdf_path],
        )
