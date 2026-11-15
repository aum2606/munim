"""The message pipeline: one customer turn from inbound message to stored reply.

Deterministic Python wires the agents together (AGENTS.md: agents never call agents).
"""

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.guardrails import check_reply
from app.agents.knowledge import KnowledgeAgent
from app.agents.models import ResponderInput, RouterInput, RouterOutput, Turn
from app.agents.responder import ResponderAgent
from app.agents.router import RouterAgent
from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import Conversation, ConversationMode, Direction, Message, SenderType
from app.db.session import SessionMaker
from app.llm.base import LLMClient
from app.llm.embedder import Embedder
from app.orchestrator.dispatch import Route, route_for
from app.orchestrator.messages import canned
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
MAX_CHARS = {"playground": 1500, "whatsapp": 1000}
MAX_REGENERATIONS = 1  # one retry with the violation fed back, then hand off


@dataclass(frozen=True)
class Deps:
    llm: LLMClient
    embedder: Embedder
    settings: Settings
    sessionmaker: SessionMaker


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

        history = await chat.recent_messages(conversation_id, HISTORY_TURNS)
        turns = [
            Turn(role="customer" if m.direction == Direction.IN else "assistant", text=m.content)
            for m in history
        ]
        trigger = pending[-1]
        tenant = await TenantRepository(session, ctx).get()
        router = await RouterAgent(deps.llm, deps.sessionmaker).run(
            ctx,
            RouterInput(business_type=tenant.business_type if tenant else "business", turns=turns),
            message_id=trigger.id,
        )
        question = "\n".join(m.content for m in pending)
        reply = await _reply_for(deps, ctx, session, conversation, router, question, turns, trigger)
        await chat.add_message(
            conversation,
            direction=Direction.OUT,
            sender_type=SenderType.AI,
            content=reply,
            language=router.language,
            intent=router.intent.value,
            reply_to_id=trigger.id,
        )
        await chat.mark_handled([m.id for m in pending])
        await session.commit()


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
    route = route_for(router, deps.settings.router_confidence_threshold)
    log.info("route", route=route.value, intent=router.intent.value, confidence=router.confidence)
    if route == Route.HANDOFF:
        conversation.mode = ConversationMode.HUMAN
        return canned("handoff", router.language)
    if route == Route.OFF_TOPIC:
        return canned("off_topic", router.language)
    if route == Route.QUOTE:  # Phase 2 replaces this with the Quote agent
        return canned("quote_pending", router.language)

    max_distance = deps.settings.search_max_distance
    knowledge = KnowledgeAgent(deps.llm, deps.sessionmaker)
    toolbox = knowledge.toolbox(
        {
            "search_knowledge": lambda query: search_knowledge(
                DocumentRepository(session, ctx), deps.embedder, query, max_distance
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

    settings = await TenantRepository(session, ctx).get_settings()
    channel = conversation.channel.value
    limit = MAX_CHARS.get(channel, 1000)
    responder = ResponderAgent(deps.llm, deps.sessionmaker)
    feedback: str | None = None
    for _ in range(MAX_REGENERATIONS + 1):
        reply = await responder.run(
            ctx,
            ResponderInput(
                language=router.language,
                script=router.script,
                tone=settings.tone if settings else "friendly",
                channel=channel,
                max_chars=limit,
                answer_points=result.answer.answer_points,
                price_lines=result.price_lines,
                violation_feedback=feedback,
            ),
            message_id=trigger.id,
        )
        violations = check_reply(reply, result.allowed_paise, limit)
        if not violations:
            return reply
        log.warning("guardrail_blocked", rules=[v.rule for v in violations])
        feedback = "; ".join(v.detail for v in violations)
    # Still failing after the retry: never send it. A person takes over.
    conversation.mode = ConversationMode.HUMAN
    return canned("handoff", router.language)
