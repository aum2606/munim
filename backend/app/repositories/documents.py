import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import Chunk, Document, DocumentSource, DocumentStatus


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    content: str


class DocumentRepository:
    """Documents and their chunks. Tenant-scoped; searches only see chunks of READY documents."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    def _mine(self, *extra: ColumnElement[bool]) -> ColumnElement[bool]:
        return and_(Document.tenant_id == self._ctx.tenant_id, *extra)

    async def add(
        self,
        *,
        title: str,
        source_type: DocumentSource,
        storage_path: str | None = None,
        status: DocumentStatus = DocumentStatus.PENDING,
    ) -> Document:
        document = Document(
            tenant_id=self._ctx.tenant_id,
            title=title,
            source_type=source_type,
            storage_path=storage_path,
            status=status,
        )
        self._session.add(document)
        await self._session.flush()
        return document

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self._session.scalar(
            select(Document).where(self._mine(Document.id == document_id))
        )

    async def browse(self, *, faq: bool) -> list[Document]:
        is_faq = Document.source_type == DocumentSource.FAQ
        result = await self._session.scalars(
            select(Document)
            .where(self._mine(is_faq if faq else ~is_faq))
            .order_by(Document.created_at.desc())
        )
        return list(result)

    async def delete(self, document_id: uuid.UUID) -> None:
        await self._session.execute(delete(Document).where(self._mine(Document.id == document_id)))

    async def set_status(
        self, document_id: uuid.UUID, status: DocumentStatus, error: str | None = None
    ) -> None:
        await self._session.execute(
            update(Document)
            .where(self._mine(Document.id == document_id))
            .values(status=status, error=error)
        )

    async def replace_chunks(self, document_id: uuid.UUID, texts: list[str]) -> None:
        """Swap in new chunk text. Embeddings are filled in afterwards by the worker."""
        await self._session.execute(
            delete(Chunk).where(
                Chunk.tenant_id == self._ctx.tenant_id, Chunk.document_id == document_id
            )
        )
        self._session.add_all(
            Chunk(
                tenant_id=self._ctx.tenant_id,
                document_id=document_id,
                position=position,
                content=text,
            )
            for position, text in enumerate(texts)
        )
        await self._session.flush()

    async def chunks_without_embedding(self, document_id: uuid.UUID) -> list[Chunk]:
        result = await self._session.scalars(
            select(Chunk)
            .where(
                Chunk.tenant_id == self._ctx.tenant_id,
                Chunk.document_id == document_id,
                Chunk.embedding.is_(None),
            )
            .order_by(Chunk.position)
        )
        return list(result)

    async def first_chunk_texts(self, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """One chunk of text per document (FAQs have exactly one)."""
        rows = await self._session.execute(
            select(Chunk.document_id, Chunk.content).where(
                Chunk.tenant_id == self._ctx.tenant_id, Chunk.document_id.in_(document_ids)
            )
        )
        return {document_id: content for document_id, content in rows}

    async def chunk_texts(self, document_id: uuid.UUID) -> list[str]:
        result = await self._session.scalars(
            select(Chunk.content)
            .where(Chunk.tenant_id == self._ctx.tenant_id, Chunk.document_id == document_id)
            .order_by(Chunk.position)
        )
        return list(result)

    # --- search -----------------------------------------------------------------------------

    def _searchable(self) -> ColumnElement[bool]:
        return and_(Chunk.tenant_id == self._ctx.tenant_id, Document.status == DocumentStatus.READY)

    async def by_vector(
        self, vector: list[float], limit: int, max_distance: float
    ) -> list[ChunkHit]:
        distance = Chunk.embedding.cosine_distance(vector)
        rows = await self._session.execute(
            select(Chunk.id, Chunk.document_id, Document.title, Chunk.content)
            .join(Document, Document.id == Chunk.document_id)
            .where(self._searchable(), Chunk.embedding.is_not(None), distance <= max_distance)
            .order_by(distance)
            .limit(limit)
        )
        return [ChunkHit(*row) for row in rows]

    async def by_text(self, tsquery: str, limit: int) -> list[ChunkHit]:
        query = func.to_tsquery("simple", tsquery)
        rows = await self._session.execute(
            select(Chunk.id, Chunk.document_id, Document.title, Chunk.content)
            .join(Document, Document.id == Chunk.document_id)
            .where(self._searchable(), Chunk.tsv.op("@@")(query))
            .order_by(func.ts_rank(Chunk.tsv, query).desc())
            .limit(limit)
        )
        return [ChunkHit(*row) for row in rows]
