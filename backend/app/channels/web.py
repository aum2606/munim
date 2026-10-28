import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import cast
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import DomainError, NotFound
from app.core.security import token_hash
from app.core.tenant import TenantContext
from app.repositories.conversations import ConversationRepository
from app.repositories.identity import TenantRepository
from app.repositories.widget import WidgetCredentialRepository, WidgetRepository
from app.schemas.chat import MessageView, WidgetMessage, WidgetSessionView
from app.workers.queue import JobQueue


class WidgetCORSMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.widget = CORSMiddleware(
            app,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith("/api/v1/widget/"):
            await self.widget(scope, receive, send)
        else:
            await self.app(scope, receive, send)


@dataclass(frozen=True)
class WidgetContext:
    tenant: TenantContext
    session_id: UUID
    conversation_id: UUID


class WidgetRateLimiter:
    def __init__(self, redis: Redis, limit: int) -> None:
        self.redis, self.limit = redis, limit

    async def check(self, key: str) -> None:
        # Atomic INCR + TTL prevents an immortal key if a process dies between commands.
        script = (
            "local n=redis.call('INCR',KEYS[1]); "
            "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n"
        )
        count = await cast(
            Awaitable[int],
            self.redis.eval(script, 1, "widget:rate:" + sha256(key.encode()).hexdigest()),
        )
        if int(count) > self.limit:
            raise DomainError("Too many chat requests; try again shortly", 429)


class WebChannelAdapter:
    channel = "web"

    def __init__(self, session: AsyncSession, config: Settings, queue: JobQueue) -> None:
        self.session, self.config, self.queue = session, config, queue

    async def start(
        self, public_key: str, consent: bool = False, notice_version: str = ""
    ) -> WidgetSessionView:
        from app.schemas.privacy import NOTICE_VERSION

        if not consent or notice_version != NOTICE_VERSION:
            raise DomainError("Accept the current privacy notice before starting chat", 409)
        tenant = await WidgetCredentialRepository(self.session).tenant(public_key)
        return await self.start_for_tenant(TenantContext(tenant.id), public_consent=True)

    async def start_for_tenant(
        self, ctx: TenantContext, *, public_consent: bool = False
    ) -> WidgetSessionView:
        tenant = await TenantRepository(self.session, ctx).get()
        token = secrets.token_urlsafe(32)
        widget = await WidgetRepository(self.session, ctx).create_session(
            token_hash(token),
            datetime.now(UTC) + timedelta(hours=self.config.widget_session_hours),
            public_consent=public_consent,
        )
        await self.session.commit()
        return WidgetSessionView(
            session_id=widget.id,
            conversation_id=widget.conversation_id,
            token=token,
            business_name=tenant.name,
        )

    async def receive(self, ctx: WidgetContext, body: WidgetMessage) -> MessageView:
        if ctx.session_id != body.session_id:
            raise NotFound()
        if not body.content.strip():
            raise DomainError("Message cannot be blank")
        message = await ConversationRepository(self.session, ctx.tenant).receive(
            ctx.conversation_id, body.content.strip(), body.external_id
        )
        await self.session.commit()
        if message.processed_at is None:
            await self.queue.enqueue("process_message", ctx.tenant.tenant_id, message.id)
        return MessageView.model_validate(message)


async def stream_messages(
    sessions: Callable[[], AsyncSession], ctx: WidgetContext, seconds: int, once: bool = False
) -> AsyncIterator[str]:
    last: str | None = None
    for _ in range(seconds):
        async with sessions() as session:
            messages = await ConversationRepository(session, ctx.tenant).messages(
                ctx.conversation_id
            )
            serialized = (
                "["
                + ",".join(
                    MessageView.model_validate(message).model_dump_json() for message in messages
                )
                + "]"
            )
        if serialized != last:
            yield "event: messages\ndata: " + serialized + "\n\n"
            last = serialized
        else:
            yield ": keepalive\n\n"
        if once:
            return
        await asyncio.sleep(1)
