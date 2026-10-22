from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.tenant import TenantContext
from app.ingestion.documents import DocumentService
from app.llm.factory import make_embedder
from app.workers.queue import ArqJobQueue


async def ingest_document(ctx: dict[str, Any], tenant_id: str, document_id: str) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await DocumentService(
                session, TenantContext(UUID(tenant_id)), settings, ArqJobQueue(settings.redis_url)
            ).ingest(UUID(document_id), make_embedder(settings))
    finally:
        await engine.dispose()
