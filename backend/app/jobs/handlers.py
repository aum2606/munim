"""Worker job handlers. Each takes (sessionmaker, tenant context, payload) and must be safe to
run twice: a crashed worker's job is retried."""

import uuid
from typing import Any

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
from app.orchestrator.pipeline import Deps
from app.orchestrator.pipeline import process_message as run_pipeline
from app.repositories.catalog import CatalogRepository
from app.repositories.documents import DocumentRepository

log = structlog.get_logger()
_BATCH = 32


def build_handlers(embedder: Embedder, settings: Settings, llm: LLMClient) -> dict[str, Handler]:
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

    async def process_message(
        sm: SessionMaker, ctx: TenantContext, payload: dict[str, Any]
    ) -> None:
        await run_pipeline(Deps(llm, embedder, settings, sm), ctx, payload)

    return {
        "process_message": process_message,
        "embed_catalog_items": embed_catalog_items,
        "embed_document": embed_document,
        "ingest_document": ingest_document,
    }
