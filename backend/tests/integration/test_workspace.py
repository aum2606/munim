from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.core.tenant import TenantContext
from app.db.models import Role
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.gaps import KnowledgeGapRepository
from app.repositories.identity import UserRepository


class FakeQueue:
    async def enqueue(self, *job):
        pass


async def owner(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Demo",
            "business_type": "printing",
            "name": "Demo",
            "email": f"{uuid4()}@example.com",
            "password": "synthetic-password",
        },
    )
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    profile = (await client.get("/api/v1/me", headers=headers)).json()
    return headers, TenantContext(UUID(profile["tenant_id"])), UUID(profile["id"])


async def test_workspace_auth_history_gaps_traces_and_cross_tenant_access(
    client, sessions, redis_url, tmp_path
):
    a, ctx_a, user_a = await owner(client)
    b, ctx_b, user_b = await owner(client)
    app = client._transport.app
    redis = Redis.from_url(redis_url)
    app.state.redis = redis
    app.state.jobs = FakeQueue()
    app.state.settings.storage_dir = str(tmp_path)
    try:
        for path in [
            "/api/v1/conversations",
            "/api/v1/knowledge-gaps",
            "/api/v1/agent-runs",
            "/api/v1/tenant",
        ]:
            assert (await client.get(path)).status_code == 401
        assert (await client.post("/api/v1/playground/session")).status_code == 401
        created = await client.post("/api/v1/playground/session", headers=a)
        assert created.status_code == 201
        widget = created.json()
        conversation_id = UUID(widget["conversation_id"])
        message = await client.post(
            "/api/v1/widget/messages",
            headers={"Authorization": "Bearer " + widget["token"]},
            json={
                "session_id": widget["session_id"],
                "external_id": "new",
                "content": "Unsupported question",
            },
        )
        assert message.status_code == 202
        message_id = UUID(message.json()["id"])
        async with sessions() as session:
            await KnowledgeGapRepository(session, ctx_a).record("Unsupported question", message_id)
            await session.commit()
        await DatabaseRunRecorder(sessions).record(
            ctx_a,
            agent="test",
            model="fake",
            request={"text": "demo@example.com"},
            output={},
            tool_calls=[],
            latency_ms=1,
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd_micros=0,
            status="success",
            error=None,
            message_id=message_id,
        )
        assert len((await client.get("/api/v1/conversations", headers=a)).json()) == 1
        assert (await client.get("/api/v1/conversations", headers=b)).json() == []
        history = "/api/v1/conversations/" + str(conversation_id) + "/messages"
        assert (await client.get(history, headers=a)).json()[0]["content"] == "Unsupported question"
        assert (await client.get(history, headers=b)).status_code == 404
        gaps = (await client.get("/api/v1/knowledge-gaps", headers=a)).json()
        assert len(gaps) == 1
        assert (await client.get("/api/v1/knowledge-gaps", headers=b)).json() == []
        answer = "/api/v1/knowledge-gaps/" + gaps[0]["id"] + "/answer"
        assert (
            await client.post(answer, headers=b, json={"answer": "Only our tenant"})
        ).status_code == 404
        assert (await client.post(answer, headers=a, json={"answer": ""})).status_code == 422
        answered = await client.post(
            answer, headers=a, json={"answer": "The team has confirmed this policy."}
        )
        assert answered.status_code == 200 and answered.json()["status"] == "answered"
        traces = "/api/v1/agent-runs?message_id=" + str(message_id)
        result = await client.get(traces, headers=a)
        assert result.status_code == 200 and len(result.json()) == 1
        assert "demo@example.com" not in result.text
        assert (await client.get(traces, headers=b)).json() == []
        assert (await client.get("/api/v1/agent-runs?message_id=bad", headers=a)).status_code == 422
        async with sessions() as session:
            user = await UserRepository(session, ctx_a).get(user_a)
            user.role = Role.STAFF
            await session.commit()
        assert (await client.get(traces, headers=a)).status_code == 403
    finally:
        await redis.aclose()
