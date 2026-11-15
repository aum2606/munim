import uuid
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import (
    Channel,
    Conversation,
    ConversationMode,
    Customer,
    Direction,
    Message,
    SenderType,
)


class ChatRepository:
    """Customers, conversations and messages. Tenant-scoped."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    def _mine(
        self, model: type[Conversation] | type[Message] | type[Customer]
    ) -> ColumnElement[bool]:
        return model.tenant_id == self._ctx.tenant_id

    async def start_conversation(
        self, channel: Channel, customer_name: str | None = None
    ) -> Conversation:
        customer = Customer(tenant_id=self._ctx.tenant_id, name=customer_name)
        self._session.add(customer)
        await self._session.flush()
        conversation = Conversation(
            tenant_id=self._ctx.tenant_id, customer_id=customer.id, channel=channel
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        return await self._session.scalar(
            select(Conversation).where(self._mine(Conversation), Conversation.id == conversation_id)
        )

    async def list_conversations(
        self, mode: ConversationMode | None = None, limit: int = 50
    ) -> list[Conversation]:
        query = select(Conversation).where(self._mine(Conversation))
        if mode:
            query = query.where(Conversation.mode == mode)
        result = await self._session.scalars(
            query.order_by(Conversation.last_customer_msg_at.desc().nulls_last()).limit(limit)
        )
        return list(result)

    async def add_message(
        self,
        conversation: Conversation,
        *,
        direction: Direction,
        sender_type: SenderType,
        content: str,
        language: str | None = None,
        intent: str | None = None,
        reply_to_id: uuid.UUID | None = None,
    ) -> Message:
        now = datetime.now(UTC)
        message = Message(
            tenant_id=self._ctx.tenant_id,
            conversation_id=conversation.id,
            direction=direction,
            sender_type=sender_type,
            content=content,
            language=language,
            intent=intent,
            reply_to_id=reply_to_id,
            # Outbound messages need no processing; inbound ones are marked once answered.
            handled_at=now if direction == Direction.OUT else None,
        )
        self._session.add(message)
        if direction == Direction.IN:
            conversation.last_customer_msg_at = now
        else:
            conversation.last_business_msg_at = now
        await self._session.flush()
        return message

    async def messages(self, conversation_id: uuid.UUID, *, limit: int = 200) -> list[Message]:
        result = await self._session.scalars(
            select(Message)
            .where(self._mine(Message), Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
            .limit(limit)
        )
        return list(result)

    async def recent_messages(self, conversation_id: uuid.UUID, limit: int) -> list[Message]:
        result = await self._session.scalars(
            select(Message)
            .where(self._mine(Message), Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return list(reversed(list(result)))

    async def unhandled_inbound(self, conversation_id: uuid.UUID) -> list[Message]:
        result = await self._session.scalars(
            select(Message)
            .where(
                and_(
                    self._mine(Message),
                    Message.conversation_id == conversation_id,
                    Message.direction == Direction.IN,
                    Message.handled_at.is_(None),
                )
            )
            .order_by(Message.created_at, Message.id)
        )
        return list(result)

    async def mark_handled(self, message_ids: list[uuid.UUID]) -> None:
        await self._session.execute(
            update(Message)
            .where(self._mine(Message), Message.id.in_(message_ids))
            .values(handled_at=datetime.now(UTC))
        )
