from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request

from app.channels.web import WebChannelAdapter
from app.core.deps import Config, Context, Owner, Session, TraceReader
from app.core.workspace import WorkspaceService
from app.ingestion.documents import DocumentService
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.gaps import KnowledgeGapRepository
from app.schemas.chat import ConversationView, MessageView, WidgetSessionView
from app.schemas.workspace import AgentRunView, GapAnswer, GapView
from app.workers.queue import JobQueue

router = APIRouter()


@router.post("/playground/session", response_model=WidgetSessionView, status_code=201)
async def playground(
    request: Request, session: Session, ctx: Context, config: Config
) -> WidgetSessionView:
    return await WebChannelAdapter(
        session, config, cast(JobQueue, request.app.state.jobs)
    ).start_for_tenant(ctx)


@router.get("/conversations", response_model=list[ConversationView])
async def conversations(session: Session, ctx: Context) -> list[ConversationView]:
    return [
        ConversationView.model_validate(conversation)
        for conversation in await ConversationRepository(session, ctx).list()
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageView])
async def messages(conversation_id: UUID, session: Session, ctx: Context) -> list[MessageView]:
    return [
        MessageView.model_validate(message)
        for message in await ConversationRepository(session, ctx).messages(conversation_id)
    ]


@router.get("/knowledge-gaps", response_model=list[GapView])
async def gaps(session: Session, ctx: Context) -> list[GapView]:
    return [
        GapView.model_validate(gap) for gap in await KnowledgeGapRepository(session, ctx).list()
    ]


@router.post("/knowledge-gaps/{gap_id}/answer", response_model=GapView)
async def answer_gap(
    gap_id: UUID, body: GapAnswer, request: Request, session: Session, ctx: Owner, config: Config
) -> GapView:
    documents = DocumentService(session, ctx, config, cast(JobQueue, request.app.state.jobs))
    return await WorkspaceService(session, ctx, documents).answer_gap(gap_id, body.answer)


@router.get("/agent-runs", response_model=list[AgentRunView])
async def runs(
    session: Session, ctx: TraceReader, message_id: UUID | None = None
) -> list[AgentRunView]:
    return [
        AgentRunView.model_validate(run)
        for run in await AgentRunRepository(session, ctx).list(message_id)
    ]
