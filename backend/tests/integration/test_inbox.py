from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.llm import FakeEmbedder, FakeLLM
from app.llm.offline import agent_response
from app.orchestrator.locks import RedisConversationLock
from app.orchestrator.pipeline import ConversationOrchestrator
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.conversations import ConversationRepository
from tests.integration.test_workspace import owner


async def test_complaint_handoff_staff_modes_private_drafts_and_price_guard(
    client, sessions, redis_url
):
    a, ctx, _ = await owner(client)
    b, _, _ = await owner(client)
    widget = (await client.post("/api/v1/playground/session", headers=a)).json()
    conversation_id = UUID(widget["conversation_id"])
    path = f"/api/v1/conversations/{conversation_id}"
    fake = FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=agent_response)
    redis = Redis.from_url(redis_url)

    async def turn(text):
        async with sessions() as session:
            await ConversationRepository(session, ctx).receive(conversation_id, text, str(uuid4()))
            await session.commit()
            return await ConversationOrchestrator(
                session,
                ctx,
                fake,
                FakeEmbedder(),
                RedisConversationLock(redis),
                client._transport.app.state.settings,
            ).process(conversation_id)

    try:
        assert (await client.post(path + "/mode", json={"mode": "human"})).status_code == 401
        assert (
            await client.post(path + "/mode", headers=b, json={"mode": "human"})
        ).status_code == 404
        assert (
            await client.post(path + "/mode", headers=a, json={"mode": "invalid"})
        ).status_code == 422
        reply = await turn("Complaint: damaged order")
        assert reply and "team" in reply.content
        conversations = (await client.get("/api/v1/conversations?mode=human", headers=a)).json()
        assert conversations[0]["id"] == str(conversation_id)
        handoffs = (await client.get("/api/v1/handoffs", headers=a)).json()
        assert len(handoffs) == 1 and handoffs[0]["reason"] == "complaint"
        assert (await client.get("/api/v1/handoffs", headers=b)).json() == []
        assert (await client.get("/api/v1/conversations?q=damaged", headers=b)).json() == []
        calls = len(fake.calls)
        assert await turn("Please help again") is None and len(fake.calls) == calls
        body = {"content": "The team is reviewing your request.", "external_id": "staff-one"}
        assert (await client.post(path + "/messages", headers=b, json=body)).status_code == 404
        assert (
            await client.post(path + "/messages", headers=a, json={**body, "content": "INR 123.45"})
        ).status_code == 400
        assert (
            await client.post(path + "/messages", headers=a, json={**body, "content": " "})
        ).status_code == 422
        sent = await client.post(path + "/messages", headers=a, json=body)
        assert sent.status_code == 201 and sent.json()["sender_type"] == "staff"
        assert (await client.post(path + "/messages", headers=a, json=body)).json()[
            "id"
        ] == sent.json()["id"]
        assert (
            await client.post(path + "/mode", headers=a, json={"mode": "assist"})
        ).status_code == 204
        assert await turn("Hello") is None
        drafts = (await client.get(path + "/drafts", headers=a)).json()
        assert len(drafts) == 1 and "Hello!" in drafts[0]["content"]
        assert (await client.get(path + "/drafts", headers=b)).status_code == 404
        messages = (await client.get(path + "/messages", headers=a)).json()
        assert not any(entry["content"] == drafts[0]["content"] for entry in messages)
        approval = "/api/v1/reply-drafts/" + drafts[0]["id"] + "/approve"
        assert (await client.post(approval, headers=b)).status_code == 404
        assert (await client.post(approval, headers=a)).status_code == 200
        assert (await client.post(approval, headers=a)).status_code == 200
        assert await turn("Hi") is None
        stale = (await client.get(path + "/drafts", headers=a)).json()[0]
        async with sessions() as session:
            await ConversationRepository(session, ctx).receive(
                conversation_id, "Another question", "newer"
            )
            await session.commit()
        assert (
            await client.post("/api/v1/reply-drafts/" + stale["id"] + "/approve", headers=a)
        ).status_code == 409
        assert (
            await client.post(path + "/mode", headers=a, json={"mode": "ai"})
        ).status_code == 204
        assert await turn("Hello") is not None
        assert (await client.get("/api/v1/handoffs", headers=a)).json() == []
        stream = await client.get("/api/v1/conversations/stream?once=true", headers=a)
        assert stream.status_code == 200 and "event: inbox" in stream.text
        assert (
            str(conversation_id)
            not in (await client.get("/api/v1/conversations/stream?once=true", headers=b)).text
        )
    finally:
        await redis.aclose()
