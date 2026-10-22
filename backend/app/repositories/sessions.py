from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Unauthorized
from app.core.tenant import TenantContext
from app.db.models import RefreshSession


class SessionRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def create(self, user_id: UUID, token_hash: str, expires_at: datetime) -> None:
        self.session.add(
            RefreshSession(
                tenant_id=self.ctx.tenant_id,
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
        await self.session.flush()

    async def consume(self, token_hash: str, now: datetime) -> UUID:
        user_id = await self.session.scalar(
            update(RefreshSession)
            .where(
                RefreshSession.tenant_id == self.ctx.tenant_id,
                RefreshSession.token_hash == token_hash,
                RefreshSession.revoked.is_(False),
                RefreshSession.expires_at > now,
            )
            .values(revoked=True)
            .returning(RefreshSession.user_id)
        )
        if user_id is None:
            raise Unauthorized()
        return user_id

    async def revoke(self, token_hash: str) -> None:
        await self.session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.tenant_id == self.ctx.tenant_id,
                RefreshSession.token_hash == token_hash,
            )
            .values(revoked=True)
        )

    async def get(self, token_hash: str) -> RefreshSession | None:
        result = await self.session.scalars(
            select(RefreshSession).where(
                RefreshSession.tenant_id == self.ctx.tenant_id,
                RefreshSession.token_hash == token_hash,
            )
        )

        return result.one_or_none()
