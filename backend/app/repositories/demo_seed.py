from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import Role, Tenant, TenantSettings, User


class DemoSeedRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def ensure(self, name: str, business_type: str, email: str, password_hash: str) -> None:
        tenant = (
            await self.session.scalars(select(Tenant).where(Tenant.id == self.ctx.tenant_id))
        ).one_or_none()
        if tenant is None:
            self.session.add(
                Tenant(
                    id=self.ctx.tenant_id,
                    name=name,
                    business_type=business_type,
                    state_code="24",
                    address="Demo Market, Ahmedabad",
                )
            )
            await self.session.flush()
        settings = (
            await self.session.scalars(
                select(TenantSettings).where(TenantSettings.tenant_id == self.ctx.tenant_id)
            )
        ).one_or_none()
        if settings is None:
            self.session.add(
                TenantSettings(
                    tenant_id=self.ctx.tenant_id,
                    business_hours={"Monday-Saturday": "10:00-19:00 IST", "Sunday": "Closed"},
                )
            )
        owner = (
            await self.session.scalars(
                select(User).where(User.tenant_id == self.ctx.tenant_id, User.email == email)
            )
        ).first()
        if owner is None:
            self.session.add(
                User(
                    tenant_id=self.ctx.tenant_id,
                    email=email,
                    name="Demo Owner",
                    password_hash=password_hash,
                    role=Role.OWNER,
                )
            )
        await self.session.flush()
