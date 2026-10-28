from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.core.tenant import TenantContext
from app.db.models import WidgetSession
from app.repositories.identity import TenantRepository
from app.repositories.scoped import ScopedRepository


class FakeQueue:
    def __init__(self):
        self.jobs = []

    async def enqueue(self, *job):
        self.jobs.append(job)


async def register(client, sessions):
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
    profile = (
        await client.get(
            "/api/v1/me", headers={"Authorization": "Bearer " + response.json()["access_token"]}
        )
    ).json()
    ctx = TenantContext(UUID(profile["tenant_id"]))
    async with sessions() as session:
        key = (await TenantRepository(session, ctx).get()).widget_public_key
    return key, ctx


async def test_widget_session_messages_stream_validation_cors_and_isolation(
    client, sessions, redis_url
):
    redis = Redis.from_url(redis_url)
    app = client._transport.app
    app.state.redis = redis
    queue = FakeQueue()
    app.state.jobs = queue
    a, ctx_a = await register(client, sessions)
    b, ctx_b = await register(client, sessions)
    try:
        assert (
            await client.post(
                "/api/v1/widget/session",
                json={
                    "key": "invalid-widget-key-123",
                    "consent": True,
                    "notice_version": "2026-10-28",
                },
            )
        ).status_code == 401
        first = await client.post(
            "/api/v1/widget/session",
            json={"key": a, "consent": True, "notice_version": "2026-10-28"},
        )
        second = await client.post(
            "/api/v1/widget/session",
            json={"key": b, "consent": True, "notice_version": "2026-10-28"},
        )
        assert first.status_code == 201 and second.status_code == 201
        one, two = first.json(), second.json()
        auth = {"Authorization": "Bearer " + one["token"]}
        body = {
            "session_id": one["session_id"],
            "external_id": "stable-id",
            "content": "visiting cards ka rate kya hai",
        }
        assert (await client.post("/api/v1/widget/messages", json=body)).status_code == 401
        sent = await client.post("/api/v1/widget/messages", headers=auth, json=body)
        assert sent.status_code == 202, sent.text
        repeated = await client.post("/api/v1/widget/messages", headers=auth, json=body)
        assert repeated.json()["id"] == sent.json()["id"]
        mismatched = {**body, "session_id": two["session_id"]}
        assert (
            await client.post("/api/v1/widget/messages", headers=auth, json=mismatched)
        ).status_code == 404
        assert (
            await client.post("/api/v1/widget/messages", headers=auth, json={**body, "content": ""})
        ).status_code == 422
        assert (
            await client.post(
                "/api/v1/widget/messages", headers=auth, json={**body, "content": "changed"}
            )
        ).status_code == 409
        stream = await client.get(
            "/api/v1/widget/stream/" + one["session_id"] + "?once=true",
            headers={**auth, "Origin": "https://customer.example"},
        )
        assert stream.status_code == 200 and "event: messages" in stream.text
        assert "visiting cards" in stream.text
        assert stream.headers["access-control-allow-origin"] == "*"
        assert (
            await client.get(
                "/api/v1/widget/stream/" + two["session_id"] + "?once=true", headers=auth
            )
        ).status_code == 404
        other = await client.get(
            "/api/v1/widget/stream/" + two["session_id"] + "?once=true",
            headers={"Authorization": "Bearer " + two["token"]},
        )
        assert "visiting cards" not in other.text
        preflight = await client.options(
            "/api/v1/widget/messages",
            headers={
                "Origin": "https://customer.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert preflight.status_code == 200
        owner_cors = await client.options(
            "/api/v1/auth/login",
            headers={"Origin": "https://customer.example", "Access-Control-Request-Method": "POST"},
        )
        assert owner_cors.status_code == 400
        async with sessions() as session:
            stored = await ScopedRepository(session, ctx_a, WidgetSession).get(
                UUID(one["session_id"])
            )
            assert one["token"] != stored.token_hash
            stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        assert (
            await client.post("/api/v1/widget/messages", headers=auth, json=body)
        ).status_code == 401
        assert queue.jobs and all(job[0] == "process_message" for job in queue.jobs)
    finally:
        await redis.aclose()


async def test_widget_rate_limit(client, sessions, redis_url):
    redis = Redis.from_url(redis_url)
    app = client._transport.app
    app.state.redis = redis
    key, ctx = await register(client, sessions)
    app.state.settings.widget_rate_per_minute = 1
    try:
        assert (
            await client.post(
                "/api/v1/widget/session",
                json={"key": key, "consent": True, "notice_version": "2026-10-28"},
            )
        ).status_code == 201
        assert (
            await client.post(
                "/api/v1/widget/session",
                json={"key": key, "consent": True, "notice_version": "2026-10-28"},
            )
        ).status_code == 429
    finally:
        await redis.aclose()
