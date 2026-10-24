import re
from uuid import UUID

import httpx
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.guardrails import GuardrailViolation, check_reply
from app.agents.knowledge import KnowledgeAgent
from app.agents.responder import ResponderAgent
from app.agents.router import RouterAgent
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models import Message
from app.db.models.conversation import ConversationMode
from app.llm import Embedder, LLMClient
from app.llm.types import ToolCall
from app.orchestrator.localized import fallback, greeting, grounded_message
from app.orchestrator.locks import ConversationLock
from app.orchestrator.requirements import RequirementsFlow
from app.quotes.approval import QuoteApproval
from app.quotes.service import QuoteService
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.gaps import KnowledgeGapRepository
from app.repositories.identity import TenantRepository
from app.repositories.quotes import QuoteRepository
from app.repositories.search import SearchRepository
from app.schemas.agents import AgentMessage, Intent, KnowledgeInput, ResponderInput, RouterInput
from app.tools.catalog_lookup import CatalogLookup, get_business_info
from app.tools.search import KnowledgeSearch

KNOWLEDGE_INTENTS = {
    Intent.PRODUCT_INFO,
    Intent.AVAILABILITY,
    Intent.PRICING,
    Intent.POLICY,
    Intent.GENERAL_FAQ,
}


class ConversationOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        llm: LLMClient,
        embedder: Embedder,
        lock: ConversationLock,
        settings: Settings,
    ) -> None:
        self.session, self.ctx, self.llm, self.embedder, self.lock, self.settings = (
            session,
            ctx,
            llm,
            embedder,
            lock,
            settings,
        )
        self.conversations = ConversationRepository(session, ctx)

    async def process(self, conversation_id: UUID) -> Message | None:
        await self.conversations.get(conversation_id)
        async with self.lock.hold(self.ctx.tenant_id, conversation_id):
            conversation = await self.conversations.get(conversation_id)
            pending = await self.conversations.pending(conversation_id)
            if not pending:
                return None
            if conversation.mode != ConversationMode.AI:
                await self.conversations.finish(
                    conversation_id, pending, None, intent="human_request", language="en"
                )
                await self.session.commit()
                return None
            history = await self.conversations.messages(conversation_id, 8)
            tenant_repository = TenantRepository(self.session, self.ctx)
            tenant = await tenant_repository.get()
            settings = await tenant_repository.settings()
            question = "\n".join(message.content for message in pending)[-4000:]
            message_id = pending[-1].id
            language, intent = "en", Intent.GENERAL_FAQ
            text = ""
            citations: list[str] = []
            handoff = False
            gap_logged = False
            try:
                route = await RouterAgent(self.llm).run(
                    self.ctx,
                    RouterInput(
                        messages=[
                            AgentMessage(direction=message.direction.value, content=message.content)
                            for message in history
                        ],
                        business_type=tenant.business_type,
                        active_flow=conversation.active_flow,
                    ),
                    message_id=message_id,
                )
                language, intent = route.language, route.intent
                if route.confidence < self.settings.router_confidence_threshold or intent in {
                    Intent.HUMAN_REQUEST,
                    Intent.COMPLAINT,
                    Intent.NEGOTIATION,
                }:
                    handoff = True
                    text = fallback(language)
                elif (
                    intent == Intent.QUOTE_REQUEST
                    or conversation.active_flow.get("kind") == "quote"
                ):
                    async with self.session.begin_nested():
                        state, text = await RequirementsFlow(
                            self.session, self.ctx, self.llm
                        ).collect(conversation_id, message_id, question, tenant.business_type)
                        if state["ready_for_quote"]:
                            quote = await QuoteService(
                                self.session, self.ctx, self.settings
                            ).create_from_requirements(conversation_id, message_id, self.llm)
                            lines = await QuoteRepository(self.session, self.ctx).lines(quote.id)
                            if (
                                settings.auto_send_quotes
                                and quote.total_paise < settings.auto_send_limit_paise
                                and not any(line.needs_owner_pricing for line in lines)
                                and (
                                    not any(line.gst_rate for line in lines)
                                    or (tenant.gstin and tenant.state_code)
                                )
                            ):
                                await QuoteApproval(self.session, self.ctx, self.settings).send(
                                    quote.id, quote.version, automated=True
                                )
                            text = (
                                "Your quote is ready for the team to review. "
                                "They will confirm the exact price shortly."
                            )
                            if quote.sent_at:
                                text = "Your quotation has been prepared and sent below."
                        check_reply(text, set(), [text])
                elif intent == Intent.GREETING:
                    text = greeting(language)
                elif intent in {Intent.SPAM, Intent.OFF_TOPIC}:
                    text = "Please ask about our business products, services or policies."
                elif intent not in KNOWLEDGE_INTENTS:
                    text = fallback(language)
                else:
                    agent = KnowledgeAgent(self.llm)
                    repository = SearchRepository(self.session, self.ctx)
                    catalog = CatalogLookup(repository, self.embedder)
                    search = KnowledgeSearch(repository, self.embedder)
                    product_facts = await agent.call_tool(
                        "lookup_catalog", lambda: catalog.lookup_catalog(question)
                    )
                    document_facts = await agent.call_tool(
                        "search_knowledge", lambda: search.search_knowledge(question)
                    )
                    business = await agent.call_tool(
                        "get_business_info", lambda: get_business_info(tenant_repository)
                    )
                    if intent in {Intent.PRICING, Intent.AVAILABILITY, Intent.PRODUCT_INFO}:
                        facts = product_facts.facts
                    else:
                        facts = document_facts.facts
                    if not facts:
                        query = question.lower()
                        if (
                            (tenant.address and re.search(r"address|where|location", query))
                            or (
                                settings.business_hours
                                and re.search(r"hours|open|timing|khula|khuli", query)
                            )
                            or re.search(r"business name|shop name", query)
                        ):
                            facts = business.facts
                    answer = await agent.run(
                        self.ctx,
                        KnowledgeInput(question=question, facts=facts),
                        message_id=message_id,
                        tools_used=[
                            ToolCall(name=name, arguments={"query": question})
                            for name in agent.allowed_tools
                        ],
                    )
                    selected = agent.grounded_facts(answer, facts)
                    citations = [fact.ref for fact in selected]
                    trusted = grounded_message(language, [fact.text for fact in selected])
                    allowed = {fact.price.paise for fact in facts if fact.price is not None}
                    body = ResponderInput(
                        question=question,
                        language=language,
                        tone=settings.tone,
                        trusted_messages=[trusted],
                        violation=None,
                    )
                    responder = ResponderAgent(self.llm)
                    for attempt in range(2):
                        candidate = await responder.run(self.ctx, body, message_id=message_id)
                        try:
                            check_reply(
                                candidate.text, allowed, [trusted], settings.max_auto_discount_pct
                            )
                            text = candidate.text
                            break
                        except GuardrailViolation as error:
                            if attempt:
                                raise
                            body = body.model_copy(update={"violation": error.message})
                    # Recheck the final boundary, including fallback paths below.
                    check_reply(text, allowed, [trusted], settings.max_auto_discount_pct)
            except (
                DomainError,
                ValidationError,
                ValueError,
                httpx.HTTPError,
                PermissionError,
            ) as error:
                handoff = isinstance(error, GuardrailViolation) or isinstance(
                    error, PermissionError
                )
                await KnowledgeGapRepository(self.session, self.ctx).record(question, message_id)
                gap_logged = True
                text = fallback(language)
                citations = []
            if text == fallback(language):
                # Unsupported intents and confidence fallbacks also leave an owner-visible gap.
                if not gap_logged and (intent not in KNOWLEDGE_INTENTS or handoff):
                    await KnowledgeGapRepository(self.session, self.ctx).record(
                        question, message_id
                    )
                check_reply(text, set(), [fallback(language)])
            elif intent not in KNOWLEDGE_INTENTS:
                check_reply(text, set(), [text])
            latest = await AgentRunRepository(self.session, self.ctx).latest_id(message_id)
            outbound = await self.conversations.finish(
                conversation_id,
                pending,
                text,
                intent=intent.value,
                language=language,
                agent_run_id=latest,
                citations=citations,
                handoff=handoff,
            )
            await self.session.commit()
            return outbound
