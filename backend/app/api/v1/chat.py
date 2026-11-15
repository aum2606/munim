import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import CtxDep, SessionDep, SettingsDep
from app.core.errors import NotFoundError
from app.db.models import AgentRun, Conversation, ConversationMode, Message
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.chat import ChatRepository
from app.schemas.chat import (
    AgentRunOut,
    ConversationOut,
    MessageOut,
    PlaygroundSend,
    PlaygroundSent,
)
from app.services.playground import PlaygroundService

router = APIRouter(tags=["chat"])


@router.post(
    "/playground/messages", response_model=PlaygroundSent, status_code=status.HTTP_202_ACCEPTED
)
async def playground_send(
    body: PlaygroundSend, ctx: CtxDep, session: SessionDep, settings: SettingsDep
) -> PlaygroundSent:
    return await PlaygroundService(session, ctx, settings).send(body.conversation_id, body.text)


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    ctx: CtxDep,
    session: SessionDep,
    mode: Annotated[ConversationMode | None, Query()] = None,
) -> list[Conversation]:
    return await ChatRepository(session, ctx).list_conversations(mode)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def conversation_messages(
    conversation_id: uuid.UUID, ctx: CtxDep, session: SessionDep
) -> list[Message]:
    chat = ChatRepository(session, ctx)
    if await chat.get_conversation(conversation_id) is None:
        raise NotFoundError("Conversation not found")
    return await chat.messages(conversation_id)


@router.get("/agent-runs", response_model=list[AgentRunOut])
async def agent_runs(
    ctx: CtxDep, session: SessionDep, message_id: Annotated[uuid.UUID, Query()]
) -> list[AgentRun]:
    """The model calls behind one customer message (the Playground trace panel)."""
    return await AgentRunRepository(session, ctx).for_message(message_id)
