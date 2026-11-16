from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import Tenant, TenantSettings


class TenantRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    async def get(self) -> Tenant | None:
        return await self._session.get(Tenant, self._ctx.tenant_id)

    async def get_settings(self) -> TenantSettings | None:
        return await self._session.scalar(
            select(TenantSettings).where(TenantSettings.tenant_id == self._ctx.tenant_id)
        )

    async def update_profile(self, **fields: str | None) -> Tenant:
        tenant = await self.get()
        if tenant is None:
            raise LookupError("tenant not found")
        for name, value in fields.items():
            setattr(tenant, name, value)
        await self._session.flush()
        return tenant
