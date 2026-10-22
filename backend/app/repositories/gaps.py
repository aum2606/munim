from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import KnowledgeGap
from app.repositories.scoped import ScopedRepository


class KnowledgeGapRepository(ScopedRepository[KnowledgeGap]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, KnowledgeGap)

    async def record(self, question: str, message_id: UUID) -> None:
        statement = insert(KnowledgeGap).values(
            tenant_id=self.ctx.tenant_id,
            question=question.strip()[:4000],
            example_message_id=message_id,
            occurrences=1,
            status="open",
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[KnowledgeGap.tenant_id, KnowledgeGap.question],
                set_={
                    "occurrences": KnowledgeGap.occurrences + 1,
                    "example_message_id": message_id,
                    "status": "open",
                },
            )
        )
