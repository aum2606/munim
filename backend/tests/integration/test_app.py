import httpx
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base


async def test_health_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).json() == {"status": "ready"}


async def test_security_headers_and_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]


async def test_domain_errors_have_a_uniform_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/me")
    assert response.json()["error"]["code"] == "unauthorized"


async def test_migrations_match_the_models(database_url: str) -> None:
    """Fails if someone changes a model without writing a migration."""
    engine = create_async_engine(database_url)
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync_conn: compare_metadata(
                MigrationContext.configure(sync_conn, opts={"compare_type": True}), Base.metadata
            )
        )
    await engine.dispose()
    assert diff == []
