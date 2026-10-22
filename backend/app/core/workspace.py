from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models.conversation import GapStatus
from app.ingestion.documents import DocumentService
from app.repositories.gaps import KnowledgeGapRepository
from app.schemas.documents import FAQInput
from app.schemas.workspace import GapView


class WorkspaceService:
    def __init__(
        self, session: AsyncSession, ctx: TenantContext, documents: DocumentService
    ) -> None:
        self.session, self.ctx, self.documents = session, ctx, documents

    async def answer_gap(self, gap_id: UUID, answer: str) -> GapView:
        repo = KnowledgeGapRepository(self.session, self.ctx)
        gap = await repo.get(gap_id)
        document = await self.documents.faq(FAQInput(question=gap.question[:300], answer=answer))
        gap.status = GapStatus.ANSWERED
        gap.answer_text = answer
        gap.converted_document_id = document.id
        await self.session.commit()
        return GapView.model_validate(gap)
