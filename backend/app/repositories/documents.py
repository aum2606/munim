from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import Chunk, Document
from app.db.models.knowledge import DocumentStatus
from app.ingestion.chunker import TextChunk
from app.repositories.scoped import ScopedRepository


class DocumentRepository(ScopedRepository[Document]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, Document)

    async def chunks(self, document_id: UUID) -> list[Chunk]:
        await self.get(document_id)
        return list(
            await self.session.scalars(
                select(Chunk)
                .where(Chunk.tenant_id == self.ctx.tenant_id, Chunk.document_id == document_id)
                .order_by(Chunk.created_at, Chunk.id)
            )
        )

    async def replace_chunks(
        self, document_id: UUID, chunks: list[TextChunk], vectors: list[list[float]]
    ) -> None:
        document = await self.get(document_id, for_update=True)
        await self.session.execute(
            delete(Chunk).where(
                Chunk.tenant_id == self.ctx.tenant_id, Chunk.document_id == document_id
            )
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.session.add(
                Chunk(
                    tenant_id=self.ctx.tenant_id,
                    document_id=document_id,
                    content=chunk.content,
                    embedding=vector,
                    source_metadata={"page": chunk.page, "section": chunk.section},
                    token_count=chunk.token_count,
                )
            )
        document.status = DocumentStatus.READY
        document.error = None
        await self.session.flush()
