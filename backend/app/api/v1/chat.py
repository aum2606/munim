import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import CtxDep, SessionDep, SettingsDep
from app.core.errors import NotFoundError
from app.db.models import AgentRun, ConversationMode, Message
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.chat import ChatRepository
from app.schemas.chat import (
    AgentRunOut,
    ConversationOut,
    MessageOut,
    PlaygroundSend,
    PlaygroundSent,
    StaffReply,
)
from app.services.conversations import ConversationService
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
) -> list[ConversationOut]:
    return await ConversationService(session, ctx).inbox(mode)


@router.post("/conversations/{conversation_id}/take-over", status_code=status.HTTP_204_NO_CONTENT)
async def take_over(conversation_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> None:
    await ConversationService(session, ctx).take_over(conversation_id)


@router.post(
    "/conversations/{conversation_id}/return-to-ai", status_code=status.HTTP_204_NO_CONTENT
)
async def return_to_ai(conversation_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> None:
    await ConversationService(session, ctx).return_to_ai(conversation_id)


@router.post(
    "/conversations/{conversation_id}/replies",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def staff_reply(
    conversation_id: uuid.UUID, body: StaffReply, ctx: CtxDep, session: SessionDep
) -> Message:
    return await ConversationService(session, ctx).staff_reply(conversation_id, body.text)


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
