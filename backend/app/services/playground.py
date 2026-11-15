import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import NotFoundError
from app.db.models import Channel, Direction, SenderType
from app.jobs.queue import enqueue
from app.repositories.chat import ChatRepository
from app.schemas.chat import PlaygroundSent


class PlaygroundService:
    """Chat as a customer from the dashboard. Same pipeline as a real channel, no Meta account."""

    def __init__(self, session: AsyncSession, ctx: TenantContext, settings: Settings) -> None:
        self._session = session
        self._ctx = ctx
        self._settings = settings
        self._chat = ChatRepository(session, ctx)

    async def send(self, conversation_id: uuid.UUID | None, text: str) -> PlaygroundSent:
        if conversation_id is None:
            conversation = await self._chat.start_conversation(
                Channel.PLAYGROUND, "Playground tester"
            )
        else:
            existing = await self._chat.get_conversation(conversation_id)
            if existing is None or existing.channel != Channel.PLAYGROUND:
                raise NotFoundError("Conversation not found")
            conversation = existing
        message = await self._chat.add_message(
            conversation, direction=Direction.IN, sender_type=SenderType.CUSTOMER, content=text
        )
        # Wait a moment so a burst of messages gets one reply (the pipeline batches them).
        due = datetime.now(UTC) + timedelta(seconds=self._settings.debounce_seconds)
        await enqueue(
            self._session,
            self._ctx,
            "process_message",
            {"conversation_id": str(conversation.id)},
            run_at=due,
        )
        return PlaygroundSent(conversation_id=conversation.id, message_id=message.id)
