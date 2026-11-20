"""Worker job handlers. Each takes (sessionmaker, tenant context, payload) and must be safe to
run twice: a crashed worker's job is retried."""

import uuid
from typing import Any

import httpx
import structlog

from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import DocumentStatus
from app.db.session import SessionMaker
from app.ingestion.chunker import chunk_text
from app.ingestion.parsers import extract_text
from app.ingestion.uploads import read_upload
from app.jobs.worker import Handler
from app.llm.base import LLMClient
from app.llm.embedder import Embedder
from app.llm.transcriber import Transcriber
from app.orchestrator.pipeline import process_message as run_pipeline
from app.orchestrator.pipeline_types import Deps
from app.repositories.catalog import CatalogRepository
from app.repositories.documents import DocumentRepository
from app.services.delivery import deliver_message as send_message
from app.services.followups import FollowUpService
from app.services.mailer import Mailer
from app.services.password_reset import send_reset_email
from app.services.voice import transcribe_message as run_transcription

log = structlog.get_logger()
_BATCH = 32


def _knowledge_handlers(embedder: Embedder, settings: Settings) -> dict[str, Handler]:
    """Turn uploads and catalogue rows into searchable vectors."""

    async def embed_catalog_items(
        sm: SessionMaker, ctx: TenantContext, payload: dict[str, Any]
    ) -> None:
        """Embed every active item that has no vector yet, a batch at a time."""
        while True:
            async with sm() as session:
                repo = CatalogRepository(session, ctx)
                items = await repo.without_embedding(_BATCH)
                if not items:
                    return
                vectors = await embedder.embed([i.search_text for i in items])
                await repo.set_embeddings({i.id: v for i, v in zip(items, vectors, strict=True)})
                await session.commit()

    async def embed_document(sm: SessionMaker, ctx: TenantContext, payload: dict[str, Any]) -> None:
        document_id = uuid.UUID(payload["document_id"])
        async with sm() as session:
            repo = DocumentRepository(session, ctx)
            if await repo.get(document_id) is None:
                return  # deleted while queued
            while chunks := await repo.chunks_without_embedding(document_id):
                batch = chunks[:_BATCH]
                vectors = await embedder.embed([c.content for c in batch])
                for chunk, vector in zip(batch, vectors, strict=True):
                    chunk.embedding = vector
                await session.flush()
            await repo.set_status(document_id, DocumentStatus.READY)
            await session.commit()

    async def ingest_document(
        sm: SessionMaker, ctx: TenantContext, payload: dict[str, Any]
    ) -> None:
        document_id = uuid.UUID(payload["document_id"])
        async with sm() as session:
            repo = DocumentRepository(session, ctx)
            document = await repo.get(document_id)
            if document is None or document.storage_path is None:
                return
            await repo.set_status(document_id, DocumentStatus.PROCESSING)
            await session.commit()
            try:
                text = extract_text(
                    read_upload(settings.storage_dir, document.storage_path), document.source_type
                )
                texts = chunk_text(text)
                await repo.replace_chunks(document_id, texts)
                await session.commit()
            except ValueError as exc:  # our own "no text found"-style messages are safe to show
                await repo.set_status(document_id, DocumentStatus.FAILED, str(exc))
                await session.commit()
                return
            except Exception as exc:
                # Unreadable or hostile file: show a generic reason, log the class only.
                log.warning("ingest_failed", document_id=str(document_id), error=type(exc).__name__)
                await repo.set_status(
                    document_id, DocumentStatus.FAILED, "The file could not be read"
                )
                await session.commit()
                return
        await embed_document(sm, ctx, payload)

    return {
        "embed_catalog_items": embed_catalog_items,
        "embed_document": embed_document,
        "ingest_document": ingest_document,
    }


def _chat_handlers(embedder: Embedder, settings: Settings, llm: LLMClient) -> dict[str, Handler]:
    """Answer customers and draft follow-ups."""

    async def process_message(
        sm: SessionMaker, ctx: TenantContext, payload: dict[str, Any]
    ) -> None:
        await run_pipeline(Deps(llm, embedder, settings, sm), ctx, payload)

    async def create_follow_ups(
        sm: SessionMaker, ctx: TenantContext, payload: dict[str, Any]
    ) -> None:
        async with sm() as session:
            await FollowUpService(session, ctx, settings).generate()
            await session.commit()

    return {"process_message": process_message, "create_follow_ups": create_follow_ups}


def _whatsapp_handlers(
    settings: Settings, http: httpx.AsyncClient, transcriber: Transcriber | None
) -> dict[str, Handler]:
    """Send messages to WhatsApp; transcribe voice notes when a speech model is given."""

    async def deliver_message(
        sm: SessionMaker, ctx: TenantContext, payload: dict[str, Any]
    ) -> None:
        async with sm() as session:
            await send_message(session, ctx, settings, http, payload["message_id"])
            await session.commit()

    handlers: dict[str, Handler] = {"deliver_message": deliver_message}
    if transcriber is None:
        return handlers

    async def transcribe_message(
        sm: SessionMaker, ctx: TenantContext, payload: dict[str, Any]
    ) -> None:
        async with sm() as session:
            await run_transcription(
                session, ctx, settings, http, transcriber, payload["message_id"]
            )
            await session.commit()

    return {**handlers, "transcribe_message": transcribe_message}


def _mail_handlers(settings: Settings, mailer: Mailer) -> dict[str, Handler]:
    async def send_password_reset(
        sm: SessionMaker, ctx: TenantContext, payload: dict[str, Any]
    ) -> None:
        async with sm() as session:
            await send_reset_email(session, settings, mailer, uuid.UUID(payload["user_id"]))
            await session.commit()

    return {"send_password_reset": send_password_reset}


def build_handlers(
    embedder: Embedder,
    settings: Settings,
    llm: LLMClient,
    http: httpx.AsyncClient | None = None,
    transcriber: Transcriber | None = None,
    mailer: Mailer | None = None,
) -> dict[str, Handler]:
    """Every job the worker can run. WhatsApp delivery needs an HTTP client and voice-note
    transcription also a speech model: without them those jobs are not registered."""
    handlers = {
        **_knowledge_handlers(embedder, settings),
        **_chat_handlers(embedder, settings, llm),
    }
    if http is not None:
        handlers.update(_whatsapp_handlers(settings, http, transcriber))
    if mailer is not None:
        handlers.update(_mail_handlers(settings, mailer))
    return handlers
