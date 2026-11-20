"""The live inbox: who needs a person, taking a chat over, replying, handing it back to the AI."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp import window_open
from app.core.context import TenantContext
from app.core.errors import ConflictError, NotFoundError
from app.db.models import Channel, Conversation, ConversationMode, Message, SenderType
from app.repositories.chat import ChatRepository
from app.schemas.chat import ConversationOut
from app.services.outbound import send_to_customer

_PREVIEW_CHARS = 80


class ConversationService:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._chat = ChatRepository(session, ctx)

    async def inbox(self, mode: ConversationMode | None) -> list[ConversationOut]:
        conversations = await self._chat.list_conversations(mode)
        ids = [c.id for c in conversations]
        customers = await self._chat.customers_by_id([c.customer_id for c in conversations])
        last = await self._chat.last_messages(ids)
        now = datetime.now(UTC)
        out: list[ConversationOut] = []
        for c in conversations:
            customer = customers.get(c.customer_id)
            preview = last[c.id].content[:_PREVIEW_CHARS] if c.id in last else None
            item = ConversationOut.model_validate(c)
            item.customer_name = customer.name if customer else None
            item.customer_phone = customer.phone if customer else None
            item.last_message = preview
            item.can_reply = c.channel != Channel.WHATSAPP or window_open(
                c.last_customer_msg_at, now
            )
            out.append(item)
        return out

    async def take_over(self, conversation_id: uuid.UUID) -> Conversation:
        conversation = await self._get(conversation_id)
        conversation.mode = ConversationMode.HUMAN  # the AI stays silent from the next turn on
        return conversation

    async def return_to_ai(self, conversation_id: uuid.UUID) -> Conversation:
        conversation = await self._get(conversation_id)
        conversation.mode = ConversationMode.AI
        return conversation

    async def staff_reply(self, conversation_id: uuid.UUID, text: str) -> Message:
        """A person answers. Replying also takes the chat over, so the AI cannot talk over them."""
        conversation = await self._get(conversation_id)
        if conversation.channel == Channel.WHATSAPP and not window_open(
            conversation.last_customer_msg_at, datetime.now(UTC)
        ):
            raise ConflictError(
                "More than 24 hours have passed since the customer wrote, so WhatsApp will not "
                "deliver a free-form reply. Message them from your own phone."
            )
        conversation.mode = ConversationMode.HUMAN
        return await send_to_customer(
            self._chat, conversation, sender_type=SenderType.STAFF, content=text
        )

    async def _get(self, conversation_id: uuid.UUID) -> Conversation:
        conversation = await self._chat.get_conversation(conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found")
        return conversation
