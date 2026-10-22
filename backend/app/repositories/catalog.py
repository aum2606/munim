from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import CatalogItem
from app.repositories.scoped import ScopedRepository
from app.schemas.catalog import CatalogInput


class CatalogRepository(ScopedRepository[CatalogItem]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, CatalogItem)

    async def upsert(self, catalog: CatalogInput, embedding: list[float]) -> CatalogItem:
        values = catalog.model_dump()
        statement = insert(CatalogItem).values(
            tenant_id=self.ctx.tenant_id, embedding=embedding, **values
        )
        returning = statement.on_conflict_do_update(
            index_elements=[CatalogItem.tenant_id, CatalogItem.sku],
            set_={**values, "embedding": embedding},
        ).returning(CatalogItem)
        result = (
            await self.session.scalars(returning.execution_options(populate_existing=True))
        ).one()
        return result

    async def update(
        self, resource_id: UUID, catalog: CatalogInput, embedding: list[float]
    ) -> CatalogItem:
        existing = await self.get(resource_id)
        for field, value in catalog.model_dump().items():
            setattr(existing, field, value)
        existing.embedding = embedding
        await self.session.flush()
        return existing

    async def by_sku(self, sku: str) -> CatalogItem | None:
        return (
            await self.session.scalars(
                select(CatalogItem).where(
                    CatalogItem.tenant_id == self.ctx.tenant_id,
                    CatalogItem.sku == sku,
                    CatalogItem.is_active.is_(True),
                )
            )
        ).one_or_none()
