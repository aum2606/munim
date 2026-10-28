import json
from pathlib import Path

import pytest
from redis.asyncio import Redis

from app.core.config import Settings
from app.db.models.conversation import ConversationMode
from app.llm import FakeEmbedder, FakeLLM
from app.llm.offline import agent_response
from app.llm.types import LLMResponse
from app.orchestrator.locks import RedisConversationLock
from app.orchestrator.pipeline import ConversationOrchestrator
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.conversations import ConversationRepository
from app.repositories.gaps import KnowledgeGapRepository
from tests.integration.test_pipeline import setup

ATTACKS = json.loads(Path(__file__).with_name("injection_suite.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", ATTACKS, ids=[case["attack"] for case in ATTACKS])
@pytest.mark.parametrize(
    "with_attack", [False, True], ids=["compromised_output", "customer_injection"]
)
async def test_compromised_model_cannot_deliver_injected_reply(
    sessions, redis_url, case, with_attack
):
    ctx, conversation_id, _, _, _ = await setup(
        sessions,
        "visiting cards price" + (". UNTRUSTED_ATTACK " + case["attack"] if with_attack else ""),
    )

    def compromised(request):
        if request.agent == "responder":
            return LLMResponse(output={"text": case["reply"]})
        response = agent_response(request)
        if request.agent == "router":
            response.output["intent"] = "pricing"
        return response

    llm = FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=compromised)
    redis = Redis.from_url(redis_url)
    try:
        async with sessions() as session:
            reply = await ConversationOrchestrator(
                session, ctx, llm, FakeEmbedder(), RedisConversationLock(redis), Settings()
            ).process(conversation_id)
            assert reply is not None and case["reply"] not in reply.content
            responder_calls = [call for call in llm.calls if call.agent == "responder"]
            if not with_attack or responder_calls:
                assert len(responder_calls) == 2
                assert (
                    await ConversationRepository(session, ctx).get(conversation_id)
                ).mode == ConversationMode.HUMAN
            else:
                from app.orchestrator.localized import fallback

                assert reply.content == fallback("en")
            assert await KnowledgeGapRepository(session, ctx).list()
            assert all("UNTRUSTED_ATTACK" not in call.system for call in llm.calls)
    finally:
        await redis.aclose()
