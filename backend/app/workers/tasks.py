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
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await DocumentService(
                session, TenantContext(UUID(tenant_id)), settings, ArqJobQueue(settings.redis_url)
            ).ingest(UUID(document_id), make_embedder(settings))
    finally:
        await engine.dispose()


async def process_message(ctx: dict[str, Any], tenant_id: str, message_id: str) -> None:
    from typing import cast

    from arq import Retry
    from arq.connections import ArqRedis

    from app.core.errors import DomainError
    from app.db.models import Message
    from app.llm.factory import make_llm
    from app.orchestrator.locks import RedisConversationLock
    from app.orchestrator.pipeline import ConversationOrchestrator
    from app.repositories.agent_runs import DatabaseRunRecorder
    from app.repositories.scoped import ScopedRepository

    settings = Settings()
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant = TenantContext(UUID(tenant_id))
    try:
        async with sessions() as session:
            message = await ScopedRepository(session, tenant, Message).get(UUID(message_id))
            orchestrator = ConversationOrchestrator(
                session,
                tenant,
                make_llm(settings, DatabaseRunRecorder(sessions)),
                make_embedder(settings),
                RedisConversationLock(
                    cast(ArqRedis, ctx["redis"]), settings.llm_timeout_s * 8 + 60
                ),
                settings,
            )
            try:
                await orchestrator.process(message.conversation_id)
                await ArqJobQueue(settings.redis_url).enqueue(
                    "update_lead", tenant.tenant_id, message.id
                )
            except DomainError as error:
                if error.status_code == 409:
                    raise Retry(defer=5) from error
                raise
    finally:
        await engine.dispose()


async def update_lead(ctx: dict[str, Any], tenant_id: str, message_id: str) -> None:
    from app.core.leads import LeadService
    from app.llm.factory import make_llm
    from app.repositories.agent_runs import DatabaseRunRecorder

    settings = Settings()
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            await LeadService(
                session,
                TenantContext(UUID(tenant_id)),
                make_llm(settings, DatabaseRunRecorder(sessions)),
            ).update(UUID(message_id))
    finally:
        await engine.dispose()


async def schedule_followups(ctx: dict[str, Any]) -> None:
    from datetime import UTC, datetime

    from app.repositories.followups import scheduled_tenants
    from app.workers.queue import followup_job_id

    settings = Settings()
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine)() as session:
            now = datetime.now(UTC)
            for tenant_id in await scheduled_tenants(session):
                await ArqJobQueue(settings.redis_url).enqueue(
                    "draft_followups",
                    tenant_id,
                    followup_job_id(tenant_id, now),
                )
    finally:
        await engine.dispose()


async def draft_followups(ctx: dict[str, Any], tenant_id: str, resource_id: str) -> None:
    from app.core.followups import FollowupService

    settings = Settings()
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await FollowupService(session, TenantContext(UUID(tenant_id))).schedule()
    finally:
        await engine.dispose()
