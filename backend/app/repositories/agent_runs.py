from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import redact
from app.core.tenant import TenantContext
from app.db.models import AgentRun


class AgentRunRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def list(self, message_id: UUID | None = None) -> list[AgentRun]:
        statement = select(AgentRun).where(AgentRun.tenant_id == self.ctx.tenant_id)
        if message_id is not None:
            statement = statement.where(AgentRun.message_id == message_id)
        return list(
            await self.session.scalars(
                statement.order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(100)
            )
        )

    async def latest_id(self, message_id: UUID) -> UUID | None:
        result = await self.session.scalars(
            select(AgentRun.id)
            .where(AgentRun.tenant_id == self.ctx.tenant_id, AgentRun.message_id == message_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
        return result.one_or_none()


class DatabaseRunRecorder:
    """Independent transaction preserves failure traces if the caller rolls back."""

    def __init__(self, sessions: Callable[[], AsyncSession]) -> None:
        self.sessions = sessions

    async def record(
        self,
        ctx: TenantContext,
        *,
        agent: str,
        model: str,
        request: dict[str, Any],
        output: dict[str, Any],
        tool_calls: list[dict[str, Any]],
        latency_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd_micros: int,
        status: str,
        error: str | None,
        message_id: UUID | None,
    ) -> None:
        async with self.sessions() as session:
            session.add(
                AgentRun(
                    tenant_id=ctx.tenant_id,
                    message_id=message_id,
                    agent=agent,
                    model=model,
                    input=redact(request),
                    output=redact(output),
                    tool_calls=redact(tool_calls),
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd_micros=cost_usd_micros,
                    status=status,
                    error=error,
                )
            )
            await session.commit()
