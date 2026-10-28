from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.insights import InsightsAgent
from app.analytics.events import emit
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models.analytics import AnalyticsEventType as Event
from app.llm import LLMClient
from app.orchestrator.localized import fallback
from app.repositories.analytics import IST, AnalyticsRepository, DigestRepository, period_bounds
from app.repositories.gaps import KnowledgeGapRepository
from app.schemas.insights import (
    AnalyticsResult,
    AnalyticsTool,
    ChartSpec,
    DigestView,
    InsightAnswer,
    InsightPlan,
    InsightQuestion,
    Overview,
    Period,
)
from app.tools.analytics import AnalyticsTools

LABELS = {
    AnalyticsTool.AWAITING: "Leads waiting for your reply",
    AnalyticsTool.SILENT: "Customers who have not replied",
    AnalyticsTool.NOT_FOLLOWED: "Leads without a recent approved follow-up",
    AnalyticsTool.TOP: "Top enquired catalogue items",
    AnalyticsTool.TREND: "New conversation enquiries",
    AnalyticsTool.INTENT: "Incoming message intents",
    AnalyticsTool.FUNNEL: "Current status of quotes created in this period",
    AnalyticsTool.QUOTES: "Quotes created in this period",
    AnalyticsTool.RESPONSE: "Time to first persisted reply",
    AnalyticsTool.GAPS: "Knowledge gaps (current snapshot)",
    AnalyticsTool.CHANNEL: "New enquiries by channel",
    AnalyticsTool.LOST: "Lost lead reasons (last updated in this period)",
}


def render_answer(
    plan: InsightPlan, result: AnalyticsResult, start: datetime, end: datetime
) -> InsightAnswer:
    assert plan.tool is not None
    text = f"{LABELS[plan.tool]}: {result.total}."
    actions = ["Review the listed records before taking action."]
    chart = None
    if plan.tool == AnalyticsTool.QUOTES:
        text = (
            f"{result.total} quotes created in this period "
            f"are currently {plan.status.replace('_', ' ')}."
        )
    elif plan.tool == AnalyticsTool.TOP:
        text = (
            f"Most enquired item: {result.rows[0]['item']} "
            f"({result.rows[0]['enquiries']} enquiries)."
            if result.rows
            else "No grounded catalogue enquiries were recorded in this period."
        )
        actions = [
            "Review these items in your catalogue.",
            "Answer open knowledge gaps about these products.",
        ]
    elif plan.tool == AnalyticsTool.RESPONSE:
        row = result.rows[0]
        text = (
            f"Average first reply: {row['average_seconds']} seconds; "
            f"median: {row['median_seconds']} seconds "
            f"across {row['replied_conversations']} replied conversations."
            if row["average_seconds"] is not None
            else "No first replies are recorded for this cohort."
        )
        text += (
            " Measured at message persistence; unanswered conversations "
            "and provider delivery latency are excluded."
        )
    if plan.tool in {AnalyticsTool.AWAITING, AnalyticsTool.SILENT, AnalyticsTool.NOT_FOLLOWED}:
        actions = [
            "Open the lead to review its conversation.",
            "Prepare a follow-up for owner approval.",
        ]
        if plan.tool == AnalyticsTool.SILENT:
            text += f" Waiting at least {plan.days} days since your last message."
        if plan.tool == AnalyticsTool.NOT_FOLLOWED:
            text += f" No approved follow-up in the last {plan.days} days."
    axes = {
        AnalyticsTool.TOP: ("item", "enquiries"),
        AnalyticsTool.TREND: ("date", "enquiries"),
        AnalyticsTool.INTENT: ("intent", "messages"),
        AnalyticsTool.FUNNEL: ("status", "quotes"),
        AnalyticsTool.CHANNEL: ("channel", "enquiries"),
        AnalyticsTool.LOST: ("reason", "leads"),
    }
    if plan.tool in axes:
        x, y = axes[plan.tool]
        chart = ChartSpec(
            kind="line" if plan.tool == AnalyticsTool.TREND else "bar",
            title=LABELS[plan.tool],
            x_key=x,
            y_key=y,
            rows=result.rows,
        )
        if plan.tool not in {AnalyticsTool.TOP}:
            text = f"{LABELS[plan.tool]}: {sum(int(row[y] or 0) for row in result.rows)}."
    if result.truncated:
        text += f" Showing {len(result.rows)} of {result.total} records."
    return InsightAnswer(
        text=text,
        table=result.rows,
        columns=result.columns,
        chart_spec=chart,
        suggested_actions=actions,
        tool=plan.tool,
        period_start=start,
        period_end=end,
        total=result.total,
        truncated=result.truncated,
    )


def digest_window(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(IST)
    monday = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=local.weekday()
    )
    if local < monday + timedelta(hours=9):
        monday -= timedelta(days=7)
    return (monday - timedelta(days=7)).astimezone(UTC), monday.astimezone(UTC)


class InsightsService:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx
        self.repository = AnalyticsRepository(session, ctx)
        self.tools = AnalyticsTools(self.repository)

    async def ask(
        self, body: InsightQuestion, llm: LLMClient, now: datetime | None = None
    ) -> InsightAnswer:
        now = now or datetime.now(UTC)
        agent = InsightsAgent(llm)
        try:
            plan = await agent.run(self.ctx, body)
            start, end = period_bounds(plan.period, now)
            if plan.tool is None:
                raise DomainError("Unsupported analytics question")
            result = await agent.call_tool(
                plan.tool.value, lambda: self.tools.execute(plan, start, end)
            )
            answer = render_answer(plan, result, start, end)
            await llm.recorder.record(
                self.ctx,
                agent="insights_tools",
                model="deterministic",
                request=plan.model_dump(mode="json"),
                output={"tool": plan.tool.value, "total": answer.total},
                tool_calls=[{"name": plan.tool.value, "arguments": plan.model_dump(mode="json")}],
                latency_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd_micros=0,
                status="success",
                error=None,
                message_id=None,
            )
        except (
            DomainError,
            ValidationError,
            ValueError,
            httpx.HTTPError,
            PermissionError,
        ) as error:
            structlog.get_logger().warning("insights_unanswered", error=type(error).__name__)
            await KnowledgeGapRepository(self.session, self.ctx).record(body.question, None)
            start, end = period_bounds(Period.MONTH, now)
            answer = InsightAnswer(text=fallback("en"), period_start=start, period_end=end)
        await emit(self.session, self.ctx, Event.INSIGHT_ASKED, uuid4())
        await self.session.commit()
        return answer

    async def overview(
        self,
        period: Period = Period.MONTH,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Overview:
        if start is None or end is None:
            start, end = period_bounds(period, datetime.now(UTC))
        metrics = await self.repository.metrics(start, end)
        results = {}
        for tool in (
            AnalyticsTool.RESPONSE,
            AnalyticsTool.TREND,
            AnalyticsTool.TOP,
            AnalyticsTool.INTENT,
            AnalyticsTool.FUNNEL,
            AnalyticsTool.CHANNEL,
        ):
            results[tool] = await self.tools.execute(InsightPlan(tool=tool), start, end)
        return Overview(
            period_start=start,
            period_end=end,
            enquiries=metrics["enquiries"],
            inbound_messages=metrics["inbound"],
            closed_conversations=metrics["closed"],
            ai_resolved_conversations=metrics["ai_resolved"],
            ai_resolution_rate_pct=(
                metrics["ai_resolved"] * 100 // metrics["closed"] if metrics["closed"] else None
            ),
            first_response=results[AnalyticsTool.RESPONSE],
            trend=results[AnalyticsTool.TREND],
            top_items=results[AnalyticsTool.TOP],
            intent_mix=results[AnalyticsTool.INTENT],
            funnel=results[AnalyticsTool.FUNNEL],
            channels=results[AnalyticsTool.CHANNEL],
            open_gaps=metrics["gaps"],
        )

    async def generate_digest(self, start: datetime, end: datetime) -> DigestView:
        repository = DigestRepository(self.session, self.ctx)
        existing = await repository.for_week(start)
        if existing is None:
            overview = await self.overview(start=start, end=end)
            accepted = next(
                (row["quotes"] for row in overview.funnel.rows if row["status"] == "accepted"), 0
            )
            answer = InsightAnswer(
                text=f"This week brought {overview.enquiries} new conversation enquiries and "
                f"{overview.inbound_messages} incoming messages. "
                f"{accepted} quotes created this week "
                f"are currently accepted. You have {overview.open_gaps} open knowledge gaps now.",
                period_start=start,
                period_end=end,
                total=overview.enquiries,
                table=overview.top_items.rows,
                columns=overview.top_items.columns,
                chart_spec=ChartSpec(
                    kind="line",
                    title="Weekly enquiries",
                    x_key="date",
                    y_key="enquiries",
                    rows=overview.trend.rows,
                ),
                suggested_actions=[
                    "Review unanswered leads and prepare follow-ups.",
                    "Answer open knowledge gaps.",
                ],
            )
            existing = await repository.save(start, end, answer.model_dump(mode="json"))
        await self.session.commit()
        return DigestView(
            id=existing.id,
            week_start=existing.week_start,
            period_end=existing.period_end,
            answer=InsightAnswer.model_validate(existing.answer),
        )

    async def latest_digest(self) -> DigestView | None:
        digest = await DigestRepository(self.session, self.ctx).latest()
        if digest is None:
            return None
        await emit(self.session, self.ctx, Event.DIGEST_OPENED, f"{digest.id}:{self.ctx.user_id}")
        await self.session.commit()
        return DigestView(
            id=digest.id,
            week_start=digest.week_start,
            period_end=digest.period_end,
            answer=InsightAnswer.model_validate(digest.answer),
        )
