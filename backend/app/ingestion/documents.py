import asyncio
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import BadZipFile

import httpx
from docx.opc.exceptions import PackageNotFoundError
from pypdf.errors import PdfReadError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models.knowledge import DocumentStatus, SourceType
from app.ingestion.chunker import TextChunk, chunk_pages
from app.ingestion.parsers import parse_document
from app.llm import Embedder
from app.repositories.documents import DocumentRepository
from app.schemas.documents import DocumentView, FAQInput
from app.workers.queue import JobQueue


class DocumentService:
    def __init__(
        self, session: AsyncSession, ctx: TenantContext, settings: Settings, queue: JobQueue
    ) -> None:
        self.session, self.ctx, self.settings, self.queue = session, ctx, settings, queue
        self.documents = DocumentRepository(session, ctx)

    async def upload(
        self,
        filename: str,
        content: bytes,
        title: str | None = None,
        source: SourceType | None = None,
    ) -> DocumentView:
        suffix = Path(filename).suffix.lower()
        extensions = {".txt": SourceType.TXT, ".pdf": SourceType.PDF, ".docx": SourceType.DOCX}
        if suffix not in extensions or not content or len(content) > 5 * 1024 * 1024:
            raise DomainError("Upload a nonempty PDF, DOCX or UTF-8 TXT under 5 MB")
        source = source or extensions[suffix]
        document_id = uuid4()
        directory = Path(self.settings.storage_dir) / str(self.ctx.tenant_id)
        path = directory / (str(document_id) + suffix)
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)
        document = await self.documents.create(
            id=document_id,
            title=(title or Path(filename).name)[:200],
            source_type=source,
            storage_path=str(path.resolve()),
        )
        await self.session.commit()
        await self.queue.enqueue("ingest_document", self.ctx.tenant_id, document.id)
        return DocumentView.model_validate(document)

    async def faq(self, faq: FAQInput) -> DocumentView:
        content = faq.question.strip() + "\n\n" + faq.answer.strip()
        if len(content.split()) > 500:
            raise DomainError("Keep each FAQ under 500 words")
        return await self.upload("faq.txt", content.encode(), faq.question, SourceType.FAQ)

    async def retry(self, document_id: UUID) -> DocumentView:
        document = await self.documents.get(document_id)
        if document.status == DocumentStatus.READY:
            raise DomainError("Document is already ready", 409)
        document.status = DocumentStatus.PENDING
        document.error = None
        await self.session.commit()
        await self.queue.enqueue("ingest_document", self.ctx.tenant_id, document.id)
        return DocumentView.model_validate(document)

    async def ingest(self, document_id: UUID, embedder: Embedder) -> None:
        document = await self.documents.get(document_id)
        if document.status == DocumentStatus.READY:
            return
        document.status = DocumentStatus.PROCESSING
        await self.session.commit()
        try:
            content = await asyncio.to_thread(Path(document.storage_path).read_bytes)
            pages = await asyncio.to_thread(parse_document, content, document.source_type)
            if document.source_type == SourceType.FAQ:
                text = pages[0].content.strip()
                chunks = [TextChunk(text, 1, document.title, len(text.split()))] if text else []
            else:
                chunks = chunk_pages(pages)
            if not chunks:
                raise DomainError("No readable text found; upload a text-based document")
            vectors = await embedder.embed([chunk.content for chunk in chunks])
            await self.documents.replace_chunks(document_id, chunks, vectors)
            await self.session.commit()
        except (
            DomainError,
            ValueError,
            OSError,
            BadZipFile,
            PdfReadError,
            httpx.HTTPError,
            KeyError,
            SyntaxError,
            PackageNotFoundError,
        ) as error:
            await self.session.rollback()
            failed = await self.documents.get(document_id)
            failed.status = DocumentStatus.FAILED
            failed.error = (
                error.message
                if isinstance(error, DomainError)
                else "Document processing failed; check the file and retry"
            )
            await self.session.commit()
            # Failed jobs are visible in the dashboard; retries are explicit and idempotent.
