"""Lead stage and score. Rule-based and deterministic: a lead's score is explainable, and a model
never moves a lead between stages (BUILD_PLAN.md section 6)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import Conversation, Lead, LeadStage, QuoteStatus
from app.repositories.chat import ChatRepository
from app.repositories.leads import LeadRepository
from app.repositories.quotes import QuoteRepository

_ORDER = [
    LeadStage.NEW,
    LeadStage.ENGAGED,
    LeadStage.QUALIFIED,
    LeadStage.QUOTED,
    LeadStage.NEGOTIATING,
]
_FINAL = {LeadStage.WON, LeadStage.LOST, LeadStage.DORMANT}


@dataclass(frozen=True)
class LeadSignals:
    has_phone: bool
    requirements_filled: int
    requirements_total: int
    quote_status: QuoteStatus | None
    customer_messages: int
    hours_since_last_message: float | None
    sentiment: str | None  # from the router: positive, neutral, negative


def lead_score(s: LeadSignals) -> int:
    """0 to 100. Phone on file 15; requirements 0-25 by completeness; quote 10 (waiting for the
    owner) or 25 (sent or accepted); 4 per customer message up to 20; recency 15 / 8 / 3 within
    a day / three days / a week; sentiment +5 or -10."""
    score = 15 if s.has_phone else 0
    if s.requirements_total:
        score += 25 * min(s.requirements_filled, s.requirements_total) // s.requirements_total
    if s.quote_status in (QuoteStatus.SENT, QuoteStatus.ACCEPTED):
        score += 25
    elif s.quote_status == QuoteStatus.PENDING_APPROVAL:
        score += 10
    score += 4 * min(s.customer_messages, 5)
    hours = s.hours_since_last_message
    if hours is not None:
        score += 15 if hours < 24 else 8 if hours < 72 else 3 if hours < 168 else 0
    score += {"positive": 5, "negative": -10}.get(s.sentiment or "", 0)
    return max(0, min(100, score))


def auto_stage(
    current: LeadStage,
    *,
    customer_messages: int,
    requirements_complete: bool,
    quote_status: QuoteStatus | None,
    negotiating: bool,
) -> LeadStage:
    """The stage the evidence supports. It only moves forward; won, lost and dormant are never
    changed automatically, and an accepted quote is the one thing that wins a lead."""
    if current in _FINAL:
        return current
    if quote_status == QuoteStatus.ACCEPTED:
        return LeadStage.WON
    if negotiating:
        computed = LeadStage.NEGOTIATING
    elif quote_status in (QuoteStatus.SENT, QuoteStatus.EXPIRED):
        computed = LeadStage.QUOTED
    elif quote_status == QuoteStatus.PENDING_APPROVAL or requirements_complete:
        computed = LeadStage.QUALIFIED
    elif customer_messages >= 2:
        computed = LeadStage.ENGAGED
    else:
        computed = LeadStage.NEW
    return max(current, computed, key=_ORDER.index)


async def sync_lead(
    session: AsyncSession,
    ctx: TenantContext,
    conversation: Conversation,
    *,
    sentiment: str | None = None,
    negotiating: bool = False,
    flow: dict[str, Any] | None = None,
) -> Lead:
    """Create the conversation's lead if needed, then refresh its stage, score and value."""
    leads = LeadRepository(session, ctx)
    chat = ChatRepository(session, ctx)
    lead = await leads.for_conversation(conversation.id)
    if lead is None:
        lead = await leads.add(
            customer_id=conversation.customer_id,
            conversation_id=conversation.id,
            channel=conversation.channel,
        )
        await leads.add_event(lead, "created", actor="ai", to_value=LeadStage.NEW.value)

    customer = await chat.get_customer(conversation.customer_id)
    messages = await chat.count_inbound(conversation.id)
    quotes = await QuoteRepository(session, ctx).for_lead(lead.id)
    latest = quotes[0] if quotes else None
    flow = flow if flow is not None else dict(conversation.active_flow)
    progress = flow.get("progress") or [0, 0]
    filled, total = int(progress[0]), int(progress[1])

    last = conversation.last_customer_msg_at
    hours = (datetime.now(UTC) - last).total_seconds() / 3600 if last else None
    signals = LeadSignals(
        has_phone=bool(customer and customer.phone),
        requirements_filled=filled,
        requirements_total=total,
        quote_status=latest.status if latest else None,
        customer_messages=messages,
        hours_since_last_message=hours,
        sentiment=sentiment,
    )
    stage = auto_stage(
        lead.stage,
        customer_messages=messages,
        requirements_complete=total > 0 and filled >= total,
        quote_status=signals.quote_status,
        negotiating=negotiating,
    )
    if stage != lead.stage:
        await leads.add_event(
            lead, "stage_changed", actor="ai", from_value=lead.stage.value, to_value=stage.value
        )
        lead.stage = stage
    lead.score = lead_score(signals)
    if latest is not None:
        lead.estimated_value_paise = latest.total_paise
    if flow.get("category"):
        lead.category = str(flow["category"])
    if flow.get("filled"):
        lead.requirements = dict(flow["filled"])
    return lead
