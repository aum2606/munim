from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import OwnerDep, SessionDep
from app.schemas.metrics import OverviewOut, UsageRowOut
from app.tools.metrics import overview

router = APIRouter(tags=["metrics"])


@router.get("/metrics/overview", response_model=OverviewOut)
async def metrics_overview(
    ctx: OwnerDep, session: SessionDep, days: Annotated[int, Query(ge=1, le=365)] = 7
) -> OverviewOut:
    """Messages, leads, quotations, who needs a person and what the model cost, last N days."""
    data = await overview(session, ctx, since=datetime.now(UTC) - timedelta(days=days))
    u = data.usage
    return OverviewOut(
        days=days,
        customer_messages=data.customer_messages,
        ai_replies=data.ai_replies,
        staff_replies=data.staff_replies,
        conversations_needing_a_person=data.conversations_needing_a_person,
        open_knowledge_gaps=data.open_knowledge_gaps,
        leads_by_stage=data.leads_by_stage,
        quotes_by_status=data.quotes_by_status,
        accepted_value_paise=data.accepted_value_paise,
        turns=u.turns,
        cost_micros=u.cost_micros,
        cost_per_turn_micros=u.cost_per_turn_micros,
        unpriced_calls=u.unpriced_calls,
        first_response_p50_ms=u.first_response_p50_ms,
        first_response_p95_ms=u.first_response_p95_ms,
        usage=[UsageRowOut.model_validate(r, from_attributes=True) for r in u.rows],
    )
