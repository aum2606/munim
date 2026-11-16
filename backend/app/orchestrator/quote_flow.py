"""The quotation conversation: collect requirements, then prepare a quote for owner approval.

The model reads the customer's words and proposes slot values and catalogue matches. Everything
that matters is decided here in code: which values are accepted, when enough is known, what
things cost (the pricing engine), and that nothing reaches the customer until the owner approves.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import (
    AddonView,
    CandidateItem,
    CategoryView,
    MappingInput,
    RequirementsInput,
    RouterOutput,
    SlotSchema,
    Turn,
)
from app.agents.quote import QuoteAgent
from app.core.context import TenantContext
from app.db.models import CatalogItem, Conversation, Message, RequirementSchema
from app.orchestrator.compose import compose_reply
from app.orchestrator.leads import sync_lead
from app.orchestrator.messages import canned
from app.orchestrator.pipeline_types import Deps
from app.orchestrator.requirements import (
    apply_unknowns,
    missing_slots,
    next_questions,
    required_slots,
    slot_definitions,
    validate_slots,
)
from app.repositories.catalog import CatalogRepository
from app.repositories.leads import LeadRepository
from app.repositories.pricing_rules import PricingRuleRepository, RequirementSchemaRepository
from app.services.pricing_rules import build_rules
from app.services.quotes import MAX_QUANTITY, ProposedLine, QuoteService
from app.tools.catalog_lookup import lookup_catalog

log = structlog.get_logger()

CANDIDATE_LIMIT = 15
FALLBACK_LIMIT = 40
_NEW_FLOW: dict[str, Any] = {
    "flow": "quote",
    "status": "collecting",
    "category": None,
    "filled": {},
}


def flow_is_active(conversation: Conversation) -> bool:
    return conversation.active_flow.get("status") == "collecting"


def _category_view(schema: RequirementSchema) -> CategoryView:
    required = set(required_slots(schema.json_schema))
    slots = []
    for name, definition in slot_definitions(schema.json_schema).items():
        options = definition.get("enum") or definition.get("items", {}).get("enum", [])
        slots.append(
            SlotSchema(
                name=name,
                type=str(definition.get("type", "string")),
                description=str(definition.get("description", "")),
                options=[str(o) for o in options],
                required=name in required,
                hint=schema.question_hints.get(name, ""),
            )
        )
    return CategoryView(category=schema.category, slots=slots)


async def quote_reply(
    deps: Deps,
    ctx: TenantContext,
    session: AsyncSession,
    conversation: Conversation,
    router: RouterOutput,
    turns: list[Turn],
    trigger: Message,
) -> str:
    schemas = await RequirementSchemaRepository(session, ctx).browse()
    if not schemas:  # the owner has not said what to ask: the team follows up by hand
        return canned("quote_pending", router.language)
    by_category = {s.category: s for s in schemas}

    flow: dict[str, Any] = dict(conversation.active_flow)
    if not flow_is_active(conversation):
        flow = {**_NEW_FLOW, "filled": {}}
    agent = QuoteAgent(deps.llm, deps.sessionmaker)
    out = await agent.collect(
        ctx,
        RequirementsInput(
            categories=[_category_view(s) for s in schemas],
            category=flow.get("category"),
            filled=flow["filled"],
            turns=turns,
        ),
        message_id=trigger.id,
    )

    category = flow.get("category")
    if category not in by_category:
        category = out.category if out.category in by_category else None
    if category is None and len(by_category) == 1:
        category = next(iter(by_category))
    if category is None:  # we do not know what kind of work this is yet: ask
        flow["progress"] = [0, 0]
        return await _ask(
            deps,
            ctx,
            session,
            conversation,
            router,
            trigger,
            flow,
            [q for q in out.questions[:2]] or [_which_work(list(by_category))],
        )

    schema = by_category[category]
    filled = {**flow["filled"], **validate_slots(schema.json_schema, out.filled)}
    filled = apply_unknowns(schema.json_schema, schema.defaults, filled, out.unknown_slots)
    missing = missing_slots(schema.json_schema, filled)
    required = required_slots(schema.json_schema)
    flow.update(
        category=category, filled=filled, progress=[len(required) - len(missing), len(required)]
    )

    if missing:
        questions = next_questions(out.questions, missing, schema.question_hints)
        return await _ask(deps, ctx, session, conversation, router, trigger, flow, questions)
    return await _prepare_quote(
        deps, ctx, session, conversation, router, trigger, flow, agent, category
    )


def _which_work(options: list[str]) -> str:
    return "What would you like a quotation for? We can help with: " + ", ".join(options) + "."


async def _ask(
    deps: Deps,
    ctx: TenantContext,
    session: AsyncSession,
    conversation: Conversation,
    router: RouterOutput,
    trigger: Message,
    flow: dict[str, Any],
    questions: list[str],
) -> str:
    conversation.active_flow = flow
    await sync_lead(session, ctx, conversation, sentiment=router.sentiment, flow=flow)
    return await compose_reply(
        deps.llm,
        deps.sessionmaker,
        deps.settings,
        ctx,
        session,
        conversation,
        router,
        trigger,
        answer_points=questions,
        price_lines=[],
        allowed_paise=frozenset(),  # no money in questions
    )


async def _candidates(
    deps: Deps, ctx: TenantContext, session: AsyncSession, filled: dict[str, Any]
) -> list[CatalogItem]:
    catalog = CatalogRepository(session, ctx)
    terms = [str(v) for v in filled.values() if isinstance(v, str)]
    hits = await lookup_catalog(
        catalog, deps.embedder, terms, deps.settings.search_max_distance, CANDIDATE_LIMIT
    )
    items = [i for i in await catalog.by_ids([h.item_id for h in hits]) if i.is_active]
    if len(items) < 3:  # a small catalogue: show the model all of it
        items = [i for i in await catalog.browse(limit=FALLBACK_LIMIT) if i.is_active]
    return items


def _decimal(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


async def _prepare_quote(
    deps: Deps,
    ctx: TenantContext,
    session: AsyncSession,
    conversation: Conversation,
    router: RouterOutput,
    trigger: Message,
    flow: dict[str, Any],
    agent: QuoteAgent,
    category: str,
) -> str:
    items = await _candidates(deps, ctx, session, flow["filled"])
    rules = PricingRuleRepository(session, ctx)
    candidates = []
    addons_by_sku: dict[str, set[str]] = {}
    for item in items:
        addons = build_rules(await rules.applying_to(item)).addons
        addons_by_sku[item.sku.lower()] = {a.code for a in addons}
        candidates.append(
            CandidateItem(
                sku=item.sku,
                name=item.name,
                unit=item.unit,
                aliases=item.aliases[:5],
                addons=[AddonView(code=a.code, name=a.name) for a in addons],
            )
        )
    proposal = await agent.propose(
        ctx,
        MappingInput(category=category, requirements=flow["filled"], candidates=candidates),
        message_id=trigger.id,
    )

    by_sku = {i.sku.lower(): i for i in items}
    proposed: list[ProposedLine] = []
    for line in proposal.lines:
        matched: CatalogItem | None = by_sku.get((line.sku or "").lower())  # made-up SKU: none
        quantity = _decimal(line.quantity)
        if quantity is None or not 0 < quantity <= MAX_QUANTITY:
            quantity = Decimal(1)
            matched = None  # an unreadable quantity: the owner will fix it
        allowed_addons = addons_by_sku.get((line.sku or "").lower(), set())
        proposed.append(
            ProposedLine(
                description=line.description or (matched.name if matched else "Requested item"),
                item_id=matched.id if matched else None,
                quantity=quantity,
                width=_decimal(line.width) if line.width is not None else None,
                height=_decimal(line.height) if line.height is not None else None,
                addon_codes=tuple(c for c in line.addon_codes if c in allowed_addons),
            )
        )
    proposed += [ProposedLine(d[:200], None, Decimal(1)) for d in proposal.unmapped if d.strip()]
    if not proposed:
        summary = ", ".join(f"{k}: {v}" for k, v in flow["filled"].items())
        proposed = [ProposedLine(f"Custom requirement ({summary})"[:200], None, Decimal(1))]

    lead = await sync_lead(session, ctx, conversation, sentiment=router.sentiment, flow=flow)
    quote, notes = await QuoteService(session, ctx, deps.settings).create(lead.id, proposed)
    leads = LeadRepository(session, ctx)
    await leads.add_event(
        lead, "quote_created", actor="ai", note="; ".join([quote.quote_number, *notes])[:500]
    )
    flow.update(status="done", quote_id=str(quote.id))
    conversation.active_flow = flow
    await sync_lead(session, ctx, conversation, sentiment=router.sentiment, flow=flow)
    log.info("quote_created", quote_id=str(quote.id), lines=len(proposed))
    # The customer is told it is coming, never what it costs: the owner approves first.
    return canned("quote_pending", router.language)
