"""The message pipeline: one customer turn from inbound message to stored reply.

Deterministic Python wires the agents together (AGENTS.md: agents never call agents).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge import KnowledgeAgent
from app.agents.models import Intent, RouterInput, RouterOutput, Turn
from app.agents.router import RouterAgent
from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import LLMOutputError, LLMUnavailableError
from app.db.models import Conversation, ConversationMode, Direction, Message, SenderType
from app.orchestrator.compose import compose_reply
from app.orchestrator.dispatch import Route, route_for
from app.orchestrator.leads import sync_lead
from app.orchestrator.messages import canned
from app.orchestrator.pipeline_types import Deps
from app.orchestrator.quote_flow import flow_is_active, quote_reply
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.catalog import CatalogRepository
from app.repositories.chat import ChatRepository
from app.repositories.documents import DocumentRepository
from app.repositories.gaps import KnowledgeGapRepository
from app.repositories.tenant import TenantRepository
from app.tools.business_info import get_business_info
from app.tools.catalog_lookup import lookup_catalog
from app.tools.search import search_knowledge

log = structlog.get_logger()

HISTORY_TURNS = 8


async def process_message(deps: Deps, ctx: TenantContext, payload: dict[str, Any]) -> None:
    """Job handler. Answers everything the customer has sent since the last reply, in one turn."""
    conversation_id = uuid.UUID(payload["conversation_id"])
    async with deps.sessionmaker() as session:
        # Serialise turns per conversation: a burst of messages becomes exactly one reply.
        await session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(str(conversation_id), 0)))
        )
        chat = ChatRepository(session, ctx)
        conversation = await chat.get_conversation(conversation_id)
        pending = await chat.unhandled_inbound(conversation_id) if conversation else []
        if conversation is None or not pending:
            return
        if conversation.mode == ConversationMode.HUMAN:  # a person owns this chat: stay silent
            await chat.mark_handled([m.id for m in pending])
            await session.commit()
            return

        if await _over_budget(session, ctx, deps.settings):
            spoken = await chat.last_language(conversation_id) or "en"
            log.warning("model_budget_reached", tenant_id=str(ctx.tenant_id))
            conversation.mode = ConversationMode.HUMAN  # a person takes over; the AI stays silent
            await chat.add_message(
                conversation,
                direction=Direction.OUT,
                sender_type=SenderType.AI,
                content=canned("handoff", spoken),
                language=spoken,
                reply_to_id=pending[-1].id,
            )
            await chat.mark_handled([m.id for m in pending])
            await session.commit()
            return

        history = await chat.recent_messages(conversation_id, HISTORY_TURNS)
        turns = [
            Turn(role="customer" if m.direction == Direction.IN else "assistant", text=m.content)
            for m in history
        ]
        trigger = pending[-1]
        tenant = await TenantRepository(session, ctx).get()
        language: str | None = None
        intent: str | None = None
        try:
            router = await RouterAgent(deps.llm, deps.sessionmaker).run(
                ctx,
                RouterInput(
                    business_type=tenant.business_type if tenant else "business",
                    turns=turns,
                    quote_flow_active=flow_is_active(conversation),
                ),
                message_id=trigger.id,
            )
            language, intent = router.language, router.intent.value
            question = "\n".join(m.content for m in pending)
            reply = await _reply_for(
                deps, ctx, session, conversation, router, question, turns, trigger
            )
            if route_for(router, deps.settings.router_confidence_threshold, False) not in (
                Route.OFF_TOPIC,
                Route.GREETING,
            ):
                await sync_lead(
                    session,
                    ctx,
                    conversation,
                    sentiment=router.sentiment,
                    negotiating=router.intent == Intent.NEGOTIATION,
                )
        except (LLMUnavailableError, LLMOutputError) as exc:
            # No model could help. Never leave a customer waiting in silence: a person takes over.
            log.warning("llm_failed_handoff", error=type(exc).__name__)
            conversation.mode = ConversationMode.HUMAN
            reply = canned("handoff", language or "en")
        await chat.add_message(
            conversation,
            direction=Direction.OUT,
            sender_type=SenderType.AI,
            content=reply,
            language=language,
            intent=intent,
            reply_to_id=trigger.id,
        )
        await chat.mark_handled([m.id for m in pending])
        await session.commit()


async def _over_budget(session: AsyncSession, ctx: TenantContext, settings: Settings) -> bool:
    limit = settings.daily_model_calls_per_business
    if limit <= 0:
        return False
    since = datetime.now(UTC) - timedelta(hours=24)
    return await AgentRunRepository(session, ctx).count_since(since) >= limit


async def _reply_for(
    deps: Deps,
    ctx: TenantContext,
    session: AsyncSession,
    conversation: Conversation,
    router: RouterOutput,
    question: str,
    turns: list[Turn],
    trigger: Message,
) -> str:
    route = route_for(
        router, deps.settings.router_confidence_threshold, flow_is_active(conversation)
    )
    log.info("route", route=route.value, intent=router.intent.value, confidence=router.confidence)
    if route == Route.HANDOFF:
        conversation.mode = ConversationMode.HUMAN
        return canned("handoff", router.language)
    if route == Route.OFF_TOPIC:
        return canned("off_topic", router.language)
    if route == Route.GREETING:
        return canned("greeting", router.language)
    if route == Route.QUOTE:
        return await quote_reply(deps, ctx, session, conversation, router, turns, trigger)

    max_distance = deps.settings.search_max_distance
    knowledge = KnowledgeAgent(deps.llm, deps.sessionmaker)
    toolbox = knowledge.toolbox(
        {
            "search_knowledge": lambda query, also="": search_knowledge(
                DocumentRepository(session, ctx), deps.embedder, query, max_distance, also=also
            ),
            "lookup_catalog": lambda terms: lookup_catalog(
                CatalogRepository(session, ctx), deps.embedder, terms, max_distance
            ),
            "get_business_info": lambda: get_business_info(TenantRepository(session, ctx)),
        }
    )
    result = await knowledge.run(
        ctx, question=question, turns=turns, router=router, toolbox=toolbox, message_id=trigger.id
    )
    if not result.answer.grounded:
        # Grounded or silent: log what we could not answer and say we will check.
        await KnowledgeGapRepository(session, ctx).record(
            result.answer.gap_question or question, trigger.id
        )
        return canned("confirm", router.language)

    return await compose_reply(
        deps.llm,
        deps.sessionmaker,
        deps.settings,
        ctx,
        session,
        conversation,
        router,
        trigger,
        answer_points=result.answer.answer_points,
        price_lines=result.price_lines,
        allowed_paise=result.allowed_paise,
        evidence_contacts=result.contacts,
    )
