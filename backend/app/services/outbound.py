"""The one way anything speaks to a customer: store the message, then queue its delivery."""

import uuid

from app.db.models import Channel, Conversation, Direction, Message, SenderType
from app.jobs.queue import enqueue
from app.repositories.chat import ChatRepository


async def send_to_customer(
    chat: ChatRepository,
    conversation: Conversation,
    *,
    sender_type: SenderType,
    content: str,
    language: str | None = None,
    intent: str | None = None,
    reply_to_id: uuid.UUID | None = None,
    quote_id: uuid.UUID | None = None,
) -> Message:
    """AI replies, staff replies, quote approvals and follow-ups all end here, so none forgets to
    deliver. A test fails if any other module stores an outbound message."""
    message = await chat.add_message(
        conversation,
        direction=Direction.OUT,
        sender_type=sender_type,
        content=content,
        language=language,
        intent=intent,
        reply_to_id=reply_to_id,
        quote_id=quote_id,
    )
    if conversation.channel == Channel.WHATSAPP:
        await enqueue(chat.session, chat.ctx, "deliver_message", {"message_id": str(message.id)})
    return message
