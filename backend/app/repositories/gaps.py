import re
import uuid

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import NotFoundError
from app.db.models import GapStatus, KnowledgeGap


def gap_key(question: str) -> str:
    """Normalised form used to count the same question asked again."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", question.lower())).strip()[:200]


class KnowledgeGapRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    def _mine(self, *extra: ColumnElement[bool]) -> ColumnElement[bool]:
        return and_(KnowledgeGap.tenant_id == self._ctx.tenant_id, *extra)

    async def record(self, question: str, message_id: uuid.UUID | None) -> None:
        """Log an unanswerable question, or count it again if it was asked before."""
        key = gap_key(question) or "(empty)"
        statement = insert(KnowledgeGap).values(
            id=uuid.uuid4(),
            tenant_id=self._ctx.tenant_id,
            question=question[:2000],
            question_key=key,
            example_message_id=message_id,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "question_key"],
                set_={"occurrences": KnowledgeGap.occurrences + 1},
            )
        )

    async def browse(self, status: GapStatus | None = None) -> list[KnowledgeGap]:
        query = select(KnowledgeGap).where(self._mine())
        if status:
            query = query.where(KnowledgeGap.status == status)
        result = await self._session.scalars(
            query.order_by(KnowledgeGap.occurrences.desc(), KnowledgeGap.created_at.desc())
        )
        return list(result)

    async def ignore(self, gap_id: uuid.UUID) -> KnowledgeGap:
        gap = await self.get(gap_id)
        if gap is None:
            raise NotFoundError("Knowledge gap not found")
        gap.status = GapStatus.IGNORED
        return gap

    async def get(self, gap_id: uuid.UUID) -> KnowledgeGap | None:
        return await self._session.scalar(
            select(KnowledgeGap).where(self._mine(KnowledgeGap.id == gap_id))
        )
