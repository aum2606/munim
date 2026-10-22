from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.tenant import TenantContext
from app.db.models import Role, Tenant, TenantSettings, User


class IdentityRepository:
    """Only public auth may discover an identity before a tenant is known."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def discover_login(self, email: str) -> User | None:
        result = await self.session.scalars(select(User).where(User.email == email))
        return result.one_or_none()

    async def register(
        self, name: str, business_type: str, email: str, owner_name: str, password_hash: str
    ) -> User:
        tenant = Tenant(name=name, business_type=business_type)
        self.session.add(tenant)
        await self.session.flush()
        self.session.add(TenantSettings(tenant_id=tenant.id))
        user = User(
            tenant_id=tenant.id,
            email=email,
            name=owner_name,
            password_hash=password_hash,
            role=Role.OWNER,
        )
        self.session.add(user)
        await self.session.flush()
        return user


class UserRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def get(self, user_id: UUID) -> User:
        user = await self.session.scalar(
            select(User).where(User.tenant_id == self.ctx.tenant_id, User.id == user_id)
        )
        if user is None:
            raise NotFound()
        return user

    async def list(self) -> list[User]:
        return list(
            await self.session.scalars(
                select(User).where(User.tenant_id == self.ctx.tenant_id).order_by(User.created_at)
            )
        )

    async def rename(self, user_id: UUID, name: str) -> User:
        user = await self.get(user_id)
        user.name = name
        await self.session.flush()
        return user


class TenantRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def get(self) -> Tenant:
        tenant = await self.session.scalar(select(Tenant).where(Tenant.id == self.ctx.tenant_id))
        if tenant is None:
            raise NotFound()
        return tenant

    async def settings(self) -> TenantSettings:
        settings = await self.session.scalar(
            select(TenantSettings).where(TenantSettings.tenant_id == self.ctx.tenant_id)
        )
        if settings is None:
            raise NotFound()
        return settings
