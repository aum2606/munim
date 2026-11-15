import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import NotFoundError
from app.db.models import Document, DocumentSource, DocumentStatus, GapStatus, KnowledgeGap
from app.ingestion.uploads import save_upload, sniff_document
from app.jobs.queue import enqueue
from app.repositories.documents import DocumentRepository
from app.repositories.gaps import KnowledgeGapRepository


def faq_text(question: str, answer: str) -> str:
    return f"Q: {question.strip()}\nA: {answer.strip()}"


class DocumentService:
    def __init__(self, session: AsyncSession, ctx: TenantContext, settings: Settings) -> None:
        self._session = session
        self._ctx = ctx
        self._settings = settings
        self._documents = DocumentRepository(session, ctx)

    async def upload(self, title: str | None, filename: str, content: bytes) -> Document:
        source = sniff_document(content)
        path = save_upload(self._settings.storage_dir, self._ctx.tenant_id, content, source.value)
        document = await self._documents.add(
            title=(title or filename or "Untitled")[:200], source_type=source, storage_path=path
        )
        await enqueue(
            self._session, self._ctx, "ingest_document", {"document_id": str(document.id)}
        )
        return document

    async def delete(self, document_id: uuid.UUID) -> None:
        if await self._documents.get(document_id) is None:
            raise NotFoundError("Document not found")
        await self._documents.delete(document_id)  # chunks go with it (ON DELETE CASCADE)

    # --- FAQs: one Q/A pair is one document with one chunk ---------------------------------

    async def create_faq(self, question: str, answer: str) -> Document:
        document = await self._documents.add(
            title=question[:200], source_type=DocumentSource.FAQ, status=DocumentStatus.PENDING
        )
        await self._documents.replace_chunks(document.id, [faq_text(question, answer)])
        await enqueue(self._session, self._ctx, "embed_document", {"document_id": str(document.id)})
        return document

    async def update_faq(self, document_id: uuid.UUID, question: str, answer: str) -> Document:
        document = await self._documents.get(document_id)
        if document is None or document.source_type != DocumentSource.FAQ:
            raise NotFoundError("FAQ not found")
        document.title = question[:200]
        document.status = DocumentStatus.PENDING
        await self._documents.replace_chunks(document.id, [faq_text(question, answer)])
        await enqueue(self._session, self._ctx, "embed_document", {"document_id": str(document.id)})
        return document

    async def faq_answer(self, document: Document) -> str:
        text = "\n".join(await self._documents.chunk_texts(document.id))
        return text.split("\nA: ", 1)[-1]

    async def answer_gap(self, gap_id: uuid.UUID, answer: str) -> KnowledgeGap:
        """Turn a knowledge gap into an FAQ so the bot can answer it next time."""
        gaps = KnowledgeGapRepository(self._session, self._ctx)
        gap = await gaps.get(gap_id)
        if gap is None:
            raise NotFoundError("Knowledge gap not found")
        faq = await self.create_faq(gap.question, answer)
        gap.status = GapStatus.ANSWERED
        gap.answer_text = answer
        gap.converted_document_id = faq.id
        return gap
