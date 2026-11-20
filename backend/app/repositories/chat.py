import uuid
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import (
    Channel,
    Conversation,
    ConversationMode,
    ConversationStatus,
    Customer,
    Direction,
    Message,
    SenderType,
)

_RANK = {"failed": 1, "sent": 1, "delivered": 2, "read": 3}


class ChatRepository:
    """Customers, conversations and messages. Tenant-scoped."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    @property
    def session(self) -> AsyncSession:
        return self._session

    @property
    def ctx(self) -> TenantContext:
        return self._ctx

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

    async def whatsapp_conversation(self, phone: str, name: str | None) -> Conversation:
        """The customer's open WhatsApp conversation; created with the customer on first contact."""
        customer = await self._session.scalar(
            select(Customer).where(self._mine(Customer), Customer.phone == phone)
        )
        if customer is None:
            customer = Customer(tenant_id=self._ctx.tenant_id, phone=phone, name=name)
            self._session.add(customer)
            await self._session.flush()
        elif name and not customer.name:
            customer.name = name
        conversation = await self._session.scalar(
            select(Conversation)
            .where(
                self._mine(Conversation),
                Conversation.customer_id == customer.id,
                Conversation.channel == Channel.WHATSAPP,
                Conversation.status == ConversationStatus.OPEN,
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        if conversation is None:
            conversation = Conversation(
                tenant_id=self._ctx.tenant_id, customer_id=customer.id, channel=Channel.WHATSAPP
            )
            self._session.add(conversation)
            await self._session.flush()
        return conversation

    async def add_inbound_once(
        self,
        conversation: Conversation,
        *,
        external_id: str,
        content: str,
        kind: str,
        media_id: str | None = None,
    ) -> Message | None:
        """Store a customer message unless this external id was already stored (a webhook that
        Meta delivered twice). Returns None for the duplicate."""
        try:
            async with (
                self._session.begin_nested()
            ):  # savepoint: a duplicate must not poison the transaction
                return await self.add_message(
                    conversation,
                    direction=Direction.IN,
                    sender_type=SenderType.CUSTOMER,
                    content=content,
                    external_id=external_id,
                    kind=kind,
                    media_id=media_id,
                )
        except IntegrityError:
            return None

    async def get_message(self, message_id: uuid.UUID) -> Message | None:
        return await self._session.scalar(
            select(Message).where(self._mine(Message), Message.id == message_id)
        )

    async def set_delivery_by_external_id(
        self, external_id: str, status: str, error: str | None
    ) -> None:
        """Delivery progress from Meta. It only moves forward: a late 'sent' never undoes 'read'."""
        message = await self._session.scalar(
            select(Message).where(self._mine(Message), Message.external_id == external_id)
        )
        if message is not None and _RANK.get(status, 0) >= _RANK.get(
            message.delivery_status or "", 0
        ):
            message.delivery_status = status
            message.delivery_error = error

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
        quote_id: uuid.UUID | None = None,
        external_id: str | None = None,
        kind: str = "text",
        media_id: str | None = None,
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
            quote_id=quote_id,
            # Explicit, not the server's now() (the transaction's start): two messages stored in one
            # transaction, a customer message and our reply, would tie and reorder.
            created_at=now,
            external_id=external_id,
            kind=kind,
            media_id=media_id,
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

    async def get_customer(self, customer_id: uuid.UUID) -> Customer | None:
        return await self._session.scalar(
            select(Customer).where(self._mine(Customer), Customer.id == customer_id)
        )

    async def count_inbound(self, conversation_id: uuid.UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                self._mine(Message),
                Message.conversation_id == conversation_id,
                Message.direction == Direction.IN,
            )
        )
        return int(count or 0)

    async def count_inbound_since(self, conversation_id: uuid.UUID, since: datetime) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                self._mine(Message),
                Message.conversation_id == conversation_id,
                Message.direction == Direction.IN,
                Message.created_at >= since,
            )
        )
        return int(count or 0)

    async def last_language(self, conversation_id: uuid.UUID) -> str | None:
        """The language the assistant last replied in, i.e. what the customer writes in."""
        return await self._session.scalar(
            select(Message.language)
            .where(
                self._mine(Message),
                Message.conversation_id == conversation_id,
                Message.language.is_not(None),
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )

    async def customers_by_id(self, customer_ids: list[uuid.UUID]) -> dict[uuid.UUID, Customer]:
        result = await self._session.scalars(
            select(Customer).where(self._mine(Customer), Customer.id.in_(customer_ids))
        )
        return {c.id: c for c in result}

    async def last_messages(self, conversation_ids: list[uuid.UUID]) -> dict[uuid.UUID, Message]:
        """The latest message of each conversation, for the inbox preview."""
        result = await self._session.scalars(
            select(Message)
            .where(self._mine(Message), Message.conversation_id.in_(conversation_ids))
            .ext(distinct_on(Message.conversation_id))
            .order_by(Message.conversation_id, Message.created_at.desc(), Message.id.desc())
        )
        return {m.conversation_id: m for m in result}
