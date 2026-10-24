from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.llm import FakeEmbedder, FakeLLM
from app.llm.offline import agent_response
from app.orchestrator.locks import RedisConversationLock
from app.orchestrator.pipeline import ConversationOrchestrator
from tests.integration.test_quote_approval import setup_quote
from tests.integration.test_workspace import FakeQueue
from tests.unit.test_agents import MemoryRecorder


async def test_auto_send_is_strictly_below_limit_and_never_sends_unpriced_quotes(
    client, sessions, redis_url, tmp_path
):
    auth, ctx, _, _, _ = await setup_quote(client, sessions, tmp_path)
    app = client._transport.app
    redis = Redis.from_url(redis_url)
    app.state.redis = redis
    app.state.jobs = FakeQueue()
    try:
        for limit, finishing, expected in [
            ("3245", "none", "pending_approval"),
            ("3246", "none", "sent"),
            ("999999", "foil", "pending_approval"),
        ]:
            updated = await client.put(
                "/api/v1/tenant/settings",
                headers=auth,
                json={"auto_send_quotes": True, "auto_send_limit_inr": limit},
            )
            assert updated.status_code == 200
            widget = (await client.post("/api/v1/playground/session", headers=auth)).json()
            sent = await client.post(
                "/api/v1/widget/messages",
                headers={"Authorization": "Bearer " + widget["token"]},
                json={
                    "session_id": widget["session_id"],
                    "external_id": str(uuid4()),
                    "content": (
                        "quote; item=visiting cards; quantity=500; sides=double-sided; "
                        "size=standard; material=standard; colour=colour; "
                    )
                    + f"finishing={finishing}; deadline=2026-12-20",
                },
            )
            assert sent.status_code == 202
            async with sessions() as session:
                reply = await ConversationOrchestrator(
                    session,
                    ctx,
                    FakeLLM(MemoryRecorder(), {}, fallback=agent_response),
                    FakeEmbedder(),
                    RedisConversationLock(redis),
                    app.state.settings,
                ).process(UUID(widget["conversation_id"]))
                assert reply is not None
            quotes = (await client.get("/api/v1/quotes", headers=auth)).json()
            quote = next(
                quote for quote in quotes if quote["conversation_id"] == widget["conversation_id"]
            )
            assert quote["status"] == expected
            if expected == "sent":
                assert quote["approved_by"] is None
        await client.put(
            "/api/v1/tenant/settings",
            headers=auth,
            json={"auto_send_quotes": False, "auto_send_limit_inr": "0"},
        )
    finally:
        await redis.aclose()
