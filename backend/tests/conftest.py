import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.core.config import Settings
from app.core.context import TenantContext
from app.core.security import hash_password
from app.db.session import SessionMaker, make_sessionmaker
from app.llm.fake import FakeLLM
from app.main import create_app
from app.repositories.auth import AuthRepository

PASSWORD = "correct horse battery"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A real Postgres (with pgvector) migrated to head: the migration is part of what we test."""
    with PostgresContainer("pgvector/pgvector:pg16", driver=None) as pg:
        url = pg.get_connection_url().replace("postgresql://", "postgresql+asyncpg://")
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(
        app_env="test", secret_key="t" * 40, database_url=database_url, storage_dir=str(tmp_path)
    )


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM([])


@pytest.fixture
async def sessionmaker(database_url: str) -> AsyncIterator[SessionMaker]:
    engine = create_async_engine(database_url)
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def client(
    settings: Settings, sessionmaker: SessionMaker, llm: FakeLLM
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    app.state.sessionmaker = sessionmaker  # ASGITransport does not run lifespan
    app.state.llm = llm
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


async def register(client: httpx.AsyncClient, email: str | None = None) -> tuple[str, str]:
    """Register a new business. Returns (email, access_token)."""
    email = email or unique_email()
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Test Press",
            "business_type": "printing",
            "name": "Owner",
            "email": email,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return email, response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_tenant(sessionmaker: SessionMaker) -> TenantContext:
    """Create a tenant directly (no HTTP) and return a context for it."""
    async with sessionmaker() as session:
        owner = await AuthRepository(session).create_tenant_with_owner(
            business_name="Direct Press",
            business_type="printing",
            owner_name="Owner",
            email=unique_email(),
            password_hash=hash_password(PASSWORD),
        )
        await session.commit()
        return TenantContext(tenant_id=owner.tenant_id, user_id=owner.id)
