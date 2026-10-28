from pathlib import Path
from uuid import UUID, uuid4

import yaml
from redis.asyncio import Redis

from app.agents.guardrails import check_prices
from app.core.config import Settings
from app.llm import FakeEmbedder, FakeLLM
from app.llm.fake import input_hash
from app.llm.offline import agent_response
from app.llm.types import LLMRequest, LLMResponse
from app.orchestrator.localized import grounded_message
from app.orchestrator.locks import RedisConversationLock
from app.orchestrator.pipeline import ConversationOrchestrator
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.catalog import CatalogRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.documents import DocumentRepository
from app.repositories.gaps import KnowledgeGapRepository
from app.repositories.identity import TenantRepository
from app.repositories.search import SearchRepository
from app.schemas.agents import (
    AgentMessage,
    Entities,
    Intent,
    KnowledgeInput,
    ResponderInput,
    RouterInput,
    RouterOutput,
)
from app.tools.catalog_lookup import CatalogLookup, get_business_info
from app.tools.search import KnowledgeSearch
from seeds.demo import seed_demo


class Queue:
    async def enqueue(self, *job):
        pass


async def test_seeded_widget_golden_conversations_zero_invented_prices(client, sessions, redis_url):
    embedder = FakeEmbedder()
    tenants = await seed_demo(sessions, embedder, "synthetic-unused-hash")
    # Re-running seeds must preserve counts and tenant boundaries.
    await seed_demo(sessions, embedder, "synthetic-unused-hash")
    async with sessions() as session:
        for ctx in tenants.values():
            assert len(await CatalogRepository(session, ctx).list()) == 4
            assert len(await DocumentRepository(session, ctx).list()) >= 3
    cases = yaml.safe_load(
        (Path(__file__).parent / "phase1_conversations.yaml").read_text(encoding="utf-8")
    )
    assert sum(case["tenant"] == "printing" and not case.get("gap") for case in cases) >= 20
    redis = Redis.from_url(redis_url)
    app = client._transport.app
    app.state.redis = redis
    app.state.jobs = Queue()
    widgets = {}
    try:
        for slug, ctx in tenants.items():
            async with sessions() as session:
                key = (await TenantRepository(session, ctx).get()).widget_public_key
            response = await client.post(
                "/api/v1/widget/session",
                json={"key": key, "consent": True, "notice_version": "2026-10-28"},
            )
            assert response.status_code == 201
            widgets[slug] = response.json()
        for case in cases:
            ctx = tenants[case["tenant"]]
            widget = widgets[case["tenant"]]
            conversation_id = UUID(widget["conversation_id"])
            sent = await client.post(
                "/api/v1/widget/messages",
                headers={"Authorization": "Bearer " + widget["token"]},
                json={
                    "session_id": widget["session_id"],
                    "external_id": str(uuid4()),
                    "content": case["question"],
                },
            )
            assert sent.status_code == 202
            async with sessions() as session:
                history = await ConversationRepository(session, ctx).messages(conversation_id, 8)
                router_body = RouterInput(
                    messages=[
                        AgentMessage(direction=message.direction.value, content=message.content)
                        for message in history
                    ],
                    business_type=(await TenantRepository(session, ctx).get()).business_type,
                )
                route = RouterOutput(
                    intent=Intent(case["intent"]),
                    secondary_intents=[],
                    language=case["language"],
                    script="latin",
                    entities=Entities(product=None, quantity=None, date=None),
                    mentioned_catalog_terms=[],
                    sentiment="neutral",
                    confidence=1,
                )
                repo = SearchRepository(session, ctx)
                product = (
                    await CatalogLookup(repo, embedder).lookup_catalog(case["question"])
                ).facts
                documents = (
                    await KnowledgeSearch(repo, embedder).search_knowledge(case["question"])
                ).facts
                facts = (
                    product
                    if case["intent"] in {"pricing", "availability", "product_info"}
                    else documents
                )
                if not facts and case["question"] == "shop khuli hai":
                    facts = (await get_business_info(TenantRepository(session, ctx))).facts
                knowledge_body = KnowledgeInput(question=case["question"], facts=facts)
                knowledge_request = LLMRequest(
                    agent="knowledge", system="", content=knowledge_body, output_schema={}
                )
                responder_body = ResponderInput(
                    question=case["question"],
                    language=case["language"],
                    tone="friendly",
                    trusted_messages=[
                        grounded_message(case["language"], [fact.text for fact in facts])
                    ],
                    violation=None,
                )
                scripts = {
                    (
                        "router",
                        input_hash(
                            LLMRequest(
                                agent="router", system="", content=router_body, output_schema={}
                            )
                        ),
                    ): [LLMResponse(output=route.model_dump(mode="json"))],
                    ("knowledge", input_hash(knowledge_request)): [
                        agent_response(knowledge_request)
                    ],
                    (
                        "responder",
                        input_hash(
                            LLMRequest(
                                agent="responder",
                                system="",
                                content=responder_body,
                                output_schema={},
                            )
                        ),
                    ): [LLMResponse(output={"text": responder_body.trusted_messages[0]})],
                }
                fake = FakeLLM(DatabaseRunRecorder(sessions), scripts)
                reply = await ConversationOrchestrator(
                    session, ctx, fake, embedder, RedisConversationLock(redis), Settings()
                ).process(conversation_id)
                assert reply is not None
                assert case["expected"] in reply.content, case
                check_prices(reply.content, set(case["prices"]))
                assert reply.attachments[0]["citations"] or case.get("gap")
            stream = await client.get(
                "/api/v1/widget/stream/" + widget["session_id"] + "?once=true",
                headers={"Authorization": "Bearer " + widget["token"]},
            )
            assert stream.status_code == 200 and case["expected"] in stream.text
        async with sessions() as session:
            gaps = await KnowledgeGapRepository(session, tenants["printing"]).list()
            assert len(gaps) == 1 and gaps[0].question == "Do you rent spaceships?"
    finally:
        await redis.aclose()
