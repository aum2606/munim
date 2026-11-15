import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.core.context import TenantContext
from app.db.models import AgentRunStatus
from app.db.session import SessionMaker
from app.llm.base import LLMResult
from app.repositories.agent_runs import AgentRunRepository


@dataclass
class RunHandle:
    """The agent fills this in; agent_run() writes it to agent_runs on exit."""

    output: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    result: LLMResult | None = None
    message_id: uuid.UUID | None = None


@asynccontextmanager
async def agent_run(
    sessionmaker: SessionMaker,
    ctx: TenantContext,
    *,
    agent: str,
    prompt_version: str,
    input: dict[str, Any],
) -> AsyncIterator[RunHandle]:
    """Every LLM-backed agent call runs inside this. Success and failure both leave a row.

    Uses its own session and commit, so the trace survives even if the caller's transaction
    rolls back (which is when you most want it).
    """
    handle = RunHandle()
    started = time.perf_counter()
    error: str | None = None
    try:
        yield handle
    except Exception as exc:
        error = type(exc).__name__  # class only: messages may contain customer text
        raise
    finally:
        result = handle.result
        async with sessionmaker() as session:
            await AgentRunRepository(session, ctx).add(
                agent=agent,
                prompt_version=prompt_version,
                input=input,
                output=handle.output,
                tool_calls=handle.tool_calls,
                status=AgentRunStatus.ERROR if error else AgentRunStatus.OK,
                error=error,
                provider=result.provider if result else None,
                model=result.model if result else None,
                prompt_tokens=result.prompt_tokens if result else 0,
                completion_tokens=result.completion_tokens if result else 0,
                latency_ms=round((time.perf_counter() - started) * 1000),
                message_id=handle.message_id,
            )
            await session.commit()
