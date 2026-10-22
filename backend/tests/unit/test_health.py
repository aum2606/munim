import httpx

from app.core.config import Settings
from app.main import create_app


async def test_health_does_not_require_database() -> None:
    app = create_app(Settings(secret_key="unit-test-key-with-at-least-32-characters"))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health")).json() == {"status": "ok"}
