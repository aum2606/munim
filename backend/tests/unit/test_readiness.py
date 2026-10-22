import httpx
import pytest
from redis.exceptions import ConnectionError

from app.core.config import Settings
from app.main import create_app


async def test_readiness_handles_dependency_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def database_ok(*args: object) -> None:
        return None

    async def redis_down(*args: object, **kwargs: object) -> None:
        raise ConnectionError("private database details")

    monkeypatch.setattr("app.main.check_database", database_ok)
    monkeypatch.setattr("app.main.Redis.ping", redis_down)
    app = create_app(Settings(secret_key="unit-test-key-with-at-least-32-characters"))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/ready")
            assert response.status_code == 503
            assert response.json() == {"status": "unavailable"}
            assert "private" not in response.text


async def test_worker_diagnostic_task() -> None:
    from app.workers.settings import heartbeat

    assert await heartbeat({}) == "ok"
