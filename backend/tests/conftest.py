import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.core.config import Settings
from app.main import create_app


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    # This Testcontainers version forwards size as raw Docker mount options.
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg").with_tmpfs_mount(
        "/var/lib/postgresql/data", size="size=512m"
    ) as postgres:
        url = postgres.get_connection_url().replace("postgresql+psycopg", "postgresql+asyncpg")
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        os.environ.setdefault("SECRET_KEY", "test-only-key-with-at-least-32-characters")
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        command.check(config)
        yield url
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def client(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(database_url=database_url, secret_key="test-only-key-with-at-least-32-characters")
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    from testcontainers.community.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as redis:
        yield f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0"
