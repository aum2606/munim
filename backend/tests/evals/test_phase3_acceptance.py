from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import yaml
from redis.asyncio import Redis

from app.core.followups import FollowupService
from app.db.models.conversation import ConversationMode
from app.db.models.lead import LeadStage
from app.llm import FakeEmbedder, FakeLLM
from app.llm.fake import input_hash
from app.llm.offline import agent_response
from app.llm.types import LLMRequest
from app.orchestrator.locks import RedisConversationLock
from app.orchestrator.pipeline import ConversationOrchestrator
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.conversations import ConversationRepository
from app.repositories.followups import FollowupRepository
from app.repositories.leads import LeadRepository
from app.schemas.agents import AgentMessage, RouterInput
from app.schemas.leads import HandoffInput
from tests.integration.test_quote_approval import setup_quote
from tests.integration.test_workspace import owner


async def test_phase3_scripted_complaints_stop_ai(client, sessions, redis_url):
    a, ctx, _ = await owner(client)
    redis = Redis.from_url(redis_url)
    cases = yaml.safe_load(
        (Path(__file__).parent / "phase3_conversations.yaml").read_text(encoding="utf-8")
    )
    try:
        for case in cases:
            widget = (await client.post("/api/v1/playground/session", headers=a)).json()
            conversation_id = UUID(widget["conversation_id"])
            bodies = {
                "router": RouterInput(
                    messages=[AgentMessage(direction="in", content=case["question"])],
                    business_type="printing",
                ),
                "handoff": HandoffInput(reason=case["intent"], messages=[case["question"]]),
            }
            scripts = {}
            for agent, body in bodies.items():
                request = LLMRequest(agent=agent, system="", content=body, output_schema={})
                scripts[(agent, input_hash(request))] = [agent_response(request)]
            fake = FakeLLM(DatabaseRunRecorder(sessions), scripts)
            async with sessions() as session:
                conversations = ConversationRepository(session, ctx)
                await conversations.receive(conversation_id, case["question"], "first")
                await session.commit()
                pipeline = ConversationOrchestrator(
                    session,
                    ctx,
                    fake,
                    FakeEmbedder(),
                    RedisConversationLock(redis),
                    client._transport.app.state.settings,
                )
                reply = await pipeline.process(conversation_id)
                assert reply and reply.language == case["language"]
                assert (await conversations.get(conversation_id)).mode.value == case["mode"]
                await conversations.receive(conversation_id, "Hello again", "second")
                await session.commit()
                assert await pipeline.process(conversation_id) is None
                assert len(fake.calls) == 2
    finally:
        await redis.aclose()


async def test_phase3_workflow_stages_and_silent_lead_draft(client, sessions, tmp_path):
    auth, ctx, _, widget, quote_id = await setup_quote(client, sessions, tmp_path)
    conversation_id = UUID(widget["conversation_id"])
    async with sessions() as session:
        lead = await LeadRepository(session, ctx).for_conversation(conversation_id, "printing")
        assert lead.stage == LeadStage.QUALIFIED
        lead_id = lead.id
    path = "/api/v1/quotes/" + quote_id
    assert (
        await client.post(path + "/approve", headers=auth, json={"expected_version": 1})
    ).status_code == 200
    assert (await client.get("/api/v1/leads/" + str(lead_id), headers=auth)).json()[
        "stage"
    ] == "quoted"
    now = datetime.now(UTC)
    async with sessions() as session:
        conversation = await ConversationRepository(session, ctx).get(conversation_id)
        conversation.mode = ConversationMode.AI
        conversation.last_customer_msg_at = now - timedelta(days=4)
        conversation.last_business_msg_at = now - timedelta(days=3)
        await session.commit()
        await FollowupService(session, ctx).schedule(now)
        assert any(
            draft.lead_id == lead_id for draft in await FollowupRepository(session, ctx).pending()
        )
        # Drafting never adds a customer-visible message.
        assert len(await ConversationRepository(session, ctx).messages(conversation_id)) == 2
    assert (
        await client.post(path + "/mark-accepted", headers=auth, json={"expected_version": 1})
    ).status_code == 200
    assert (await client.get("/api/v1/leads/" + str(lead_id), headers=auth)).json()[
        "stage"
    ] == "won"
    events = (await client.get("/api/v1/leads/" + str(lead_id) + "/events", headers=auth)).json()
    assert [event["to_value"] for event in events if event["event_type"] == "stage"] == [
        "qualified",
        "quoted",
        "won",
    ]
