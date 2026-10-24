from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import Followup, Lead, Tenant
from app.repositories.scoped import ScopedRepository


async def scheduled_tenants(session: AsyncSession) -> list[UUID]:
    # Infrastructure fan-out reads only the tenants table; each job below gets a TenantContext.
    return list(await session.scalars(select(Tenant.id).order_by(Tenant.id)))


class FollowupRepository(ScopedRepository[Followup]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, Followup)

    async def candidates(self, after: UUID | None = None) -> list[Lead]:
        statement = select(Lead).where(Lead.tenant_id == self.ctx.tenant_id)
        if after:
            statement = statement.where(Lead.id > after)
        return list(await self.session.scalars(statement.order_by(Lead.id).limit(100)))

    async def pending(self) -> list[Followup]:
        return list(
            await self.session.scalars(
                select(Followup)
                .where(Followup.tenant_id == self.ctx.tenant_id, Followup.status == "scheduled")
                .order_by(Followup.scheduled_at)
                .limit(200)
            )
        )

    async def schedule(
        self,
        lead_id: UUID,
        kind: str,
        source_at: datetime,
        scheduled_at: datetime,
        draft_text: str,
        requires_template: bool,
    ) -> None:
        await self.session.execute(
            insert(Followup)
            .values(
                tenant_id=self.ctx.tenant_id,
                lead_id=lead_id,
                kind=kind,
                source_at=source_at,
                scheduled_at=scheduled_at,
                draft_text=draft_text,
                status="scheduled",
                requires_template=requires_template,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    Followup.tenant_id,
                    Followup.lead_id,
                    Followup.kind,
                    Followup.source_at,
                ]
            )
        )
