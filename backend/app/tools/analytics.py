from collections.abc import Awaitable, Callable
from datetime import datetime

from app.repositories.analytics import AnalyticsRepository
from app.schemas.insights import AnalyticsResult, AnalyticsTool, InsightPlan


async def leads_awaiting_reply(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(
        plan.model_copy(update={"tool": AnalyticsTool.AWAITING}), start, end
    )


async def leads_not_followed_up(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(
        plan.model_copy(update={"tool": AnalyticsTool.NOT_FOLLOWED}), start, end
    )


async def customers_who_went_silent(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(
        plan.model_copy(update={"tool": AnalyticsTool.SILENT}), start, end
    )


async def top_enquired_items(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(plan.model_copy(update={"tool": AnalyticsTool.TOP}), start, end)


async def enquiry_trend(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(plan.model_copy(update={"tool": AnalyticsTool.TREND}), start, end)


async def intent_breakdown(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(
        plan.model_copy(update={"tool": AnalyticsTool.INTENT}), start, end
    )


async def quote_funnel(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(
        plan.model_copy(update={"tool": AnalyticsTool.FUNNEL}), start, end
    )


async def quotes_by_status(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(
        plan.model_copy(update={"tool": AnalyticsTool.QUOTES}), start, end
    )


async def avg_first_response_time(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(
        plan.model_copy(update={"tool": AnalyticsTool.RESPONSE}), start, end
    )


async def knowledge_gaps(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(plan.model_copy(update={"tool": AnalyticsTool.GAPS}), start, end)


async def channel_breakdown(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(
        plan.model_copy(update={"tool": AnalyticsTool.CHANNEL}), start, end
    )


async def lost_reasons(
    repository: AnalyticsRepository,
    plan: InsightPlan,
    start: datetime,
    end: datetime,
) -> AnalyticsResult:
    return await repository.query(plan.model_copy(update={"tool": AnalyticsTool.LOST}), start, end)


Operation = Callable[
    [AnalyticsRepository, InsightPlan, datetime, datetime], Awaitable[AnalyticsResult]
]
OPERATIONS: dict[AnalyticsTool, Operation] = {
    AnalyticsTool.AWAITING: leads_awaiting_reply,
    AnalyticsTool.NOT_FOLLOWED: leads_not_followed_up,
    AnalyticsTool.SILENT: customers_who_went_silent,
    AnalyticsTool.TOP: top_enquired_items,
    AnalyticsTool.TREND: enquiry_trend,
    AnalyticsTool.INTENT: intent_breakdown,
    AnalyticsTool.FUNNEL: quote_funnel,
    AnalyticsTool.QUOTES: quotes_by_status,
    AnalyticsTool.RESPONSE: avg_first_response_time,
    AnalyticsTool.GAPS: knowledge_gaps,
    AnalyticsTool.CHANNEL: channel_breakdown,
    AnalyticsTool.LOST: lost_reasons,
}


class AnalyticsTools:
    """Fixed read-only dispatch. Only the repository executes tenant-scoped SQL."""

    def __init__(self, repository: AnalyticsRepository) -> None:
        self.repository = repository

    async def execute(self, plan: InsightPlan, start: datetime, end: datetime) -> AnalyticsResult:
        if plan.tool is None or plan.tool not in OPERATIONS:
            raise PermissionError("Unsupported analytics tool")
        return await OPERATIONS[plan.tool](self.repository, plan, start, end)
