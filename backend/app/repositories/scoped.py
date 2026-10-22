from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.tenant import TenantContext
from app.db.base import TenantRecord


class ScopedRepository[T: TenantRecord]:
    def __init__(self, session: AsyncSession, ctx: TenantContext, model: type[T]) -> None:
        self.session, self.ctx, self.model = session, ctx, model

    async def get(self, resource_id: UUID, *, for_update: bool = False) -> T:
        statement = select(self.model).where(
            self.model.tenant_id == self.ctx.tenant_id,
            self.model.id == resource_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = (
            await self.session.scalars(statement.execution_options(populate_existing=True))
        ).one_or_none()
        if result is None:
            raise NotFound()
        return result

    async def list(self, limit: int = 100) -> list[T]:
        return list(
            await self.session.scalars(
                select(self.model)
                .where(self.model.tenant_id == self.ctx.tenant_id)
                .order_by(self.model.created_at.desc(), self.model.id)
                .limit(limit)
            )
        )

    async def create(self, **values: Any) -> T:
        resource = self.model(tenant_id=self.ctx.tenant_id, **values)
        self.session.add(resource)
        await self.session.flush()
        return resource

    async def delete(self, resource_id: UUID) -> None:
        await self.session.delete(await self.get(resource_id))
        await self.session.flush()
