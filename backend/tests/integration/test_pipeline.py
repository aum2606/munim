import asyncio
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import NotFound
from app.core.tenant import TenantContext
from app.db.models import Conversation, Customer
from app.db.models.conversation import ConversationMode
from app.llm import FakeEmbedder, FakeLLM
from app.llm.fake import input_hash
from app.llm.offline import agent_response
from app.llm.types import LLMRequest, LLMResponse
from app.orchestrator.localized import fallback, grounded_message
from app.orchestrator.locks import RedisConversationLock
from app.orchestrator.pipeline import ConversationOrchestrator
from app.repositories.agent_runs import AgentRunRepository, DatabaseRunRecorder
from app.repositories.catalog import CatalogRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.gaps import KnowledgeGapRepository
from app.repositories.identity import IdentityRepository
from app.repositories.scoped import ScopedRepository
from app.repositories.search import SearchRepository
from app.schemas.agents import AgentMessage, KnowledgeInput, ResponderInput, RouterInput
from app.schemas.catalog import CatalogInput
from app.schemas.leads import HandoffInput
from app.tools.catalog_lookup import CatalogLookup
from app.workers.queue import ArqJobQueue


async def setup(sessions, question, *, regeneration="valid"):
    async with sessions() as session:
        owner = await IdentityRepository(session).register(
            "Demo", "printing", f"{uuid4()}@example.com", "Demo", "unused"
        )
        ctx = TenantContext(owner.tenant_id)
        customer = await ScopedRepository(session, ctx, Customer).create()
        conversation = await ScopedRepository(session, ctx, Conversation).create(
            customer_id=customer.id
        )
        embedder = FakeEmbedder()
        await CatalogRepository(session, ctx).upsert(
            CatalogInput(sku="CARD", name="Visiting cards", base_price_paise=45000),
            (await embedder.embed(["visiting cards"]))[0],
        )
        message = await ConversationRepository(session, ctx).receive(
            conversation.id, question, str(uuid4())
        )
        await session.commit()
        facts = (
            await CatalogLookup(SearchRepository(session, ctx), embedder).lookup_catalog(question)
        ).facts
        router = RouterInput(
            messages=[AgentMessage(direction="in", content=question)], business_type="printing"
        )
        bodies = {"router": router, "knowledge": KnowledgeInput(question=question, facts=facts)}
        scripts = {}
        for name, body in bodies.items():
            request = LLMRequest(agent=name, system="", content=body, output_schema={})
            scripts[(name, input_hash(request))] = [agent_response(request)]
        route = agent_response(
            LLMRequest(agent="router", system="", content=router, output_schema={})
        ).output
        trusted = grounded_message(route["language"], [fact.text for fact in facts])
        responder = ResponderInput(
            question=question,
            language=route["language"],
            tone="friendly",
            trusted_messages=[trusted],
            violation=None,
        )
        response = LLMResponse(
            output={"text": trusted if regeneration == "valid" else "Injected price: \u20b91.00"}
        )
        scripts[
            (
                "responder",
                input_hash(
                    LLMRequest(agent="responder", system="", content=responder, output_schema={})
                ),
            )
        ] = [response]
        retry = responder.model_copy(
            update={"violation": "Price not returned by a tool in this turn"}
        )
        scripts[
            (
                "responder",
                input_hash(
                    LLMRequest(agent="responder", system="", content=retry, output_schema={})
                ),
            )
        ] = [
            LLMResponse(
                output={
                    "text": trusted if regeneration == "recover" else "Injected price: \u20b91.00"
                }
            )
        ]
        if regeneration == "blocked":
            body = HandoffInput(reason="guardrail_or_confidence", messages=[question])
            request = LLMRequest(agent="handoff", system="", content=body, output_schema={})
            scripts[("handoff", input_hash(request))] = [agent_response(request)]
        fake = FakeLLM(DatabaseRunRecorder(sessions), scripts)
        return ctx, conversation.id, message.id, fake, trusted


@pytest.mark.parametrize("regeneration", ["valid", "recover", "blocked"])
async def test_pipeline_regenerates_or_hands_off_and_is_idempotent(
    sessions, redis_url, regeneration
):
    question = "visiting cards ka rate kya hai"
    ctx, conversation_id, message_id, fake, trusted = await setup(
        sessions, question, regeneration=regeneration
    )
    redis = Redis.from_url(redis_url)
    try:
        async with sessions() as session:
            orchestrator = ConversationOrchestrator(
                session, ctx, fake, FakeEmbedder(), RedisConversationLock(redis), Settings()
            )
            reply = await orchestrator.process(conversation_id)
            assert reply is not None
            assert "\u20b91.00" not in reply.content
            if regeneration == "blocked":
                assert reply.content == fallback("hinglish")
                assert (
                    await ConversationRepository(session, ctx).get(conversation_id)
                ).mode == ConversationMode.HUMAN
                gaps = await KnowledgeGapRepository(session, ctx).list()
                assert len(gaps) == 1 and gaps[0].occurrences == 1
            else:
                assert reply.content == trusted and "\u20b9450.00" in reply.content
            assert await orchestrator.process(conversation_id) is None
            assert len(await ConversationRepository(session, ctx).messages(conversation_id)) == 2
            runs = await AgentRunRepository(session, ctx).list()
            assert len(runs) == (
                3 if regeneration == "valid" else 5 if regeneration == "blocked" else 4
            )
            knowledge = next(run for run in runs if run.agent == "knowledge")
            assert {call["name"] for call in knowledge.tool_calls} == {
                "lookup_catalog",
                "search_knowledge",
                "get_business_info",
            }
    finally:
        await redis.aclose()


async def test_unknown_question_logs_gap_and_tenant_and_human_modes_are_enforced(
    sessions, redis_url
):
    question = "Do you rent spaceships?"
    ctx, conversation_id, message_id, fake, _ = await setup(sessions, question)
    redis = Redis.from_url(redis_url)
    try:
        async with sessions() as session:
            orchestrator = ConversationOrchestrator(
                session, ctx, fake, FakeEmbedder(), RedisConversationLock(redis), Settings()
            )
            reply = await orchestrator.process(conversation_id)
            assert reply.content == fallback("en")
            assert len(await KnowledgeGapRepository(session, ctx).list()) == 1
            wrong = ConversationOrchestrator(
                session,
                TenantContext(uuid4()),
                fake,
                FakeEmbedder(),
                RedisConversationLock(redis),
                Settings(),
            )
            with pytest.raises(NotFound):
                await wrong.process(conversation_id)
            conversation = await ConversationRepository(session, ctx).get(conversation_id)
            conversation.mode = ConversationMode.HUMAN
            await ConversationRepository(session, ctx).receive(
                conversation_id, "another question", str(uuid4())
            )
            await session.commit()
            count = len(fake.calls)
            assert await orchestrator.process(conversation_id) is None
            assert len(fake.calls) == count
    finally:
        await redis.aclose()


async def test_two_workers_produce_one_reply(sessions, redis_url):
    ctx, conversation_id, message_id, fake, _ = await setup(sessions, "visiting cards price")
    redis = Redis.from_url(redis_url)

    async def process():
        async with sessions() as session:
            return await ConversationOrchestrator(
                session, ctx, fake, FakeEmbedder(), RedisConversationLock(redis), Settings()
            ).process(conversation_id)

    try:
        replies = await asyncio.gather(process(), process())
        assert sum(reply is not None for reply in replies) == 1
        async with sessions() as session:
            assert len(await ConversationRepository(session, ctx).messages(conversation_id)) == 2
    finally:
        await redis.aclose()


async def test_inbound_idempotency_and_durable_debounce_queue(sessions, redis_url):
    ctx, conversation_id, message_id, fake, _ = await setup(sessions, "visiting cards price")
    async with sessions() as session:
        repo = ConversationRepository(session, ctx)
        first = await repo.receive(conversation_id, "same message", "stable-external-id")
        second = await repo.receive(conversation_id, "same message", "stable-external-id")
        assert first.id == second.id
        await session.commit()
    queue = ArqJobQueue(redis_url, debounce_seconds=2)
    await queue.enqueue("process_message", ctx.tenant_id, message_id)
    await queue.enqueue("process_message", ctx.tenant_id, message_id)
    redis = Redis.from_url(redis_url)
    try:
        assert await redis.exists(f"arq:job:process_message:{ctx.tenant_id}:{message_id}")
    finally:
        await redis.aclose()
