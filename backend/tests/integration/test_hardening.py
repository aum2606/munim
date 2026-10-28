import httpx
import pytest
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.hardening import RateLimiter, RequestSafetyMiddleware
from app.ingestion.validation import validate_document
from tests.integration.test_workspace import owner


async def test_auth_and_tenant_limits_and_body_size(client):
    headers, _, _ = await owner(client)
    settings = client._transport.app.state.settings
    settings.rate_limits_enabled = True
    settings.user_rate_per_minute = 2
    for _ in range(2):
        assert (await client.get("/api/v1/me", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 429
    settings.auth_rate_per_minute = 1
    for expected in (401, 429):
        response = await client.post(
            "/api/v1/auth/login", json={"email": "missing@example.com", "password": "incorrect"}
        )
        assert response.status_code == expected
    assert response.headers["retry-after"] == "60"
    response = await client.post(
        "/api/v1/auth/login",
        content=b"x" * (settings.max_json_bytes + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in {413, 429}
    response = await client.post(
        "/api/v1/insights/ask",
        content=b"x" * (settings.max_json_bytes + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_atomic_limiter_expires_and_does_not_store_ip(redis_url):
    redis = Redis.from_url(redis_url)
    try:
        limiter = RateLimiter(redis)
        await limiter.check("synthetic-ip-key", 1)
        with pytest.raises(DomainError) as error:
            await limiter.check("synthetic-ip-key", 1)
        assert error.value.status_code == 429
        keys = await redis.keys("api:rate:*")
        assert keys and all(b"synthetic-ip-key" not in key for key in keys)
        assert all(0 < ttl <= 60 for ttl in [await redis.ttl(key) for key in keys])
    finally:
        await redis.aclose()


async def test_chunked_body_limit_before_app_executes():
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    middleware = RequestSafetyMiddleware(app, Settings(max_json_bytes=1024))

    async def content():
        yield b"x" * 800
        yield b"y" * 800

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=middleware), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/data", content=content(), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 413 and not called


@pytest.mark.parametrize(
    "content,suffix", [(b"binary\0text", ".txt"), (b"fake PDF", ".pdf"), (b"fake ZIP", ".docx")]
)
def test_disguised_document_types_are_rejected(content, suffix):
    with pytest.raises(DomainError):
        validate_document(content, suffix)
