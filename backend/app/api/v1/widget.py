from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from redis.asyncio import Redis

from app.channels.web import WebChannelAdapter, WidgetContext, WidgetRateLimiter, stream_messages
from app.core.deps import Config, Session, bearer
from app.core.errors import NotFound, Unauthorized
from app.core.security import token_hash
from app.core.tenant import TenantContext
from app.repositories.widget import WidgetCredentialRepository
from app.schemas.chat import MessageView, WidgetMessage, WidgetSessionView, WidgetStart
from app.workers.queue import JobQueue

router = APIRouter(prefix="/widget")


def adapter(request: Request, session: Session, config: Config) -> WebChannelAdapter:
    return WebChannelAdapter(session, config, cast(JobQueue, request.app.state.jobs))


async def widget_context(
    session: Session, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> WidgetContext:
    if credentials is None:
        raise Unauthorized()
    widget = await WidgetCredentialRepository(session).authenticate(
        token_hash(credentials.credentials)
    )
    return WidgetContext(TenantContext(widget.tenant_id), widget.id, widget.conversation_id)


WidgetAuth = Annotated[WidgetContext, Depends(widget_context)]


@router.post("/session", response_model=WidgetSessionView, status_code=201)
async def start(
    body: WidgetStart, request: Request, session: Session, config: Config
) -> WidgetSessionView:
    ip = request.client.host if request.client else "unknown"
    await WidgetRateLimiter(
        cast(Redis, request.app.state.redis), config.widget_rate_per_minute
    ).check("session:" + ip + ":" + body.key)
    return await adapter(request, session, config).start(body.key)


@router.post("/messages", response_model=MessageView, status_code=202)
async def message(
    body: WidgetMessage, request: Request, session: Session, config: Config, ctx: WidgetAuth
) -> MessageView:
    ip = request.client.host if request.client else "unknown"
    await WidgetRateLimiter(
        cast(Redis, request.app.state.redis), config.widget_rate_per_minute
    ).check("message:" + ip + ":" + str(ctx.tenant.tenant_id))
    return await adapter(request, session, config).receive(ctx, body)


@router.get("/stream/{session_id}")
async def stream(
    session_id: UUID,
    ctx: WidgetAuth,
    request: Request,
    session: Session,
    config: Config,
    once: bool = False,
) -> StreamingResponse:
    if session_id != ctx.session_id:
        raise NotFound()
    ip = request.client.host if request.client else "unknown"
    await WidgetRateLimiter(
        cast(Redis, request.app.state.redis), config.widget_rate_per_minute
    ).check("stream:" + ip + ":" + str(ctx.tenant.tenant_id))
    # Release the authentication transaction before the long-lived response.
    await session.rollback()
    return StreamingResponse(
        stream_messages(request.app.state.sessions, ctx, config.widget_stream_seconds, once),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
