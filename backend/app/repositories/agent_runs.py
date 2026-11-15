import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import AgentRun, AgentRunStatus


class AgentRunRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    async def add(
        self,
        *,
        agent: str,
        prompt_version: str,
        input: dict[str, Any],
        status: AgentRunStatus,
        output: dict[str, Any] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        provider: str | None = None,
        model: str | None = None,
        latency_ms: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_estimate_micros: int = 0,
        message_id: uuid.UUID | None = None,
        error: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            tenant_id=self._ctx.tenant_id,
            agent=agent,
            prompt_version=prompt_version,
            input=input,
            output=output,
            tool_calls=tool_calls or [],
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_estimate_micros=cost_estimate_micros,
            message_id=message_id,
            status=status,
            error=error,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def list_recent(self, limit: int = 50) -> list[AgentRun]:
        result = await self._session.scalars(
            select(AgentRun)
            .where(AgentRun.tenant_id == self._ctx.tenant_id)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
        return list(result)
