"""Fixed, tenant-scoped metric queries (AGENTS.md: no free-form text-to-SQL).

Cost and latency come from `agent_runs`; first-response time from the messages themselves.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Integer, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.context import TenantContext
from app.db.models import AgentRun, AgentRunStatus, Direction, Message, SenderType
from app.llm.costs import LIST_PRICES


@dataclass(frozen=True)
class UsageRow:
    agent: str
    model: str | None
    calls: int
    errors: int
    prompt_tokens: int
    completion_tokens: int
    cost_micros: int  # at list price; 0 for a model with no listed price
    p50_ms: int
    p95_ms: int


@dataclass(frozen=True)
class UsageReport:
    rows: list[UsageRow]
    turns: int  # customer messages that triggered at least one model call
    cost_micros: int
    unpriced_calls: int  # calls to a model with no listed price: the cost is understated
    cost_per_turn_micros: int
    first_response_p50_ms: int | None
    first_response_p95_ms: int | None


async def usage_report(
    session: AsyncSession, ctx: TenantContext, *, since: datetime | None = None
) -> UsageReport:
    runs = AgentRun.tenant_id == ctx.tenant_id
    if since is not None:
        runs = and_(runs, AgentRun.created_at >= since)

    grouped = await session.execute(
        select(
            AgentRun.agent,
            AgentRun.model,
            func.count(),
            func.sum(case((AgentRun.status == AgentRunStatus.ERROR, 1), else_=0).cast(Integer)),
            func.sum(AgentRun.prompt_tokens),
            func.sum(AgentRun.completion_tokens),
            func.sum(AgentRun.cost_estimate_micros),
            func.percentile_cont(0.5).within_group(AgentRun.latency_ms),
            func.percentile_cont(0.95).within_group(AgentRun.latency_ms),
        )
        .where(runs)
        .group_by(AgentRun.agent, AgentRun.model)
        .order_by(AgentRun.agent, AgentRun.model)
    )
    rows = [
        UsageRow(
            agent,
            model,
            calls,
            int(errors or 0),
            int(prompt or 0),
            int(completion or 0),
            int(cost or 0),
            round(p50 or 0),
            round(p95 or 0),
        )  # fmt: skip
        for agent, model, calls, errors, prompt, completion, cost, p50, p95 in grouped
    ]
    total_cost = sum(r.cost_micros for r in rows)
    unpriced = sum(r.calls for r in rows if r.model not in LIST_PRICES and r.model is not None)

    turns = (
        await session.scalar(
            select(func.count(func.distinct(AgentRun.message_id))).where(
                runs, AgentRun.message_id.is_not(None)
            )
        )
        or 0
    )

    inbound = aliased(Message)
    gap_ms = func.extract("epoch", Message.created_at - inbound.created_at) * 1000
    answered = [
        Message.tenant_id == ctx.tenant_id,
        Message.direction == Direction.OUT,
        Message.sender_type == SenderType.AI,
    ]
    if since is not None:
        answered.append(Message.created_at >= since)
    replies = (
        select(gap_ms.label("gap"))
        .join(inbound, inbound.id == Message.reply_to_id)
        .where(*answered)
    ).subquery()
    p50, p95 = (
        await session.execute(
            select(
                func.percentile_cont(0.5).within_group(replies.c.gap),
                func.percentile_cont(0.95).within_group(replies.c.gap),
            )
        )
    ).one()
    return UsageReport(
        rows=rows,
        turns=int(turns),
        cost_micros=total_cost,
        unpriced_calls=unpriced,
        cost_per_turn_micros=total_cost // turns if turns else 0,
        first_response_p50_ms=round(p50) if p50 is not None else None,
        first_response_p95_ms=round(p95) if p95 is not None else None,
    )
