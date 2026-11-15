import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Role, TenantContext
from app.db.models import Tenant, User


class UserRepository:
    """Tenant-scoped: every query filters by ctx.tenant_id."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    async def list(self) -> list[User]:
        result = await self._session.scalars(
            select(User).where(User.tenant_id == self._ctx.tenant_id).order_by(User.created_at)
        )
        return list(result)

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.scalar(
            select(User).where(User.id == user_id, User.tenant_id == self._ctx.tenant_id)
        )

    async def add(self, *, email: str, name: str, password_hash: str, role: Role) -> User:
        user = User(
            tenant_id=self._ctx.tenant_id,
            email=email,
            name=name,
            password_hash=password_hash,
            role=role,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_own_tenant(self) -> Tenant | None:
        return await self._session.get(Tenant, self._ctx.tenant_id)
