"""Unscoped lookups that must happen BEFORE a TenantContext exists (login, register, refresh).

Deliberately small. Everything after authentication goes through tenant-scoped repositories.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Role
from app.db.models import PasswordResetToken, RefreshToken, Tenant, TenantSettings, User


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def create_tenant_with_owner(
        self,
        *,
        business_name: str,
        business_type: str,
        owner_name: str,
        email: str,
        password_hash: str,
    ) -> User:
        tenant = Tenant(name=business_name, business_type=business_type)
        self._session.add(tenant)
        await self._session.flush()
        self._session.add(TenantSettings(tenant_id=tenant.id))
        owner = User(
            tenant_id=tenant.id,
            email=email,
            name=owner_name,
            password_hash=password_hash,
            role=Role.OWNER,
        )
        self._session.add(owner)
        await self._session.flush()
        return owner

    async def add_refresh_token(
        self, user: User, token_hash: str, expires_at: datetime
    ) -> RefreshToken:
        token = RefreshToken(
            tenant_id=user.tenant_id, user_id=user.id, token_hash=token_hash, expires_at=expires_at
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_refresh_token_for_update(self, token_hash: str) -> RefreshToken | None:
        """Row-locked so two concurrent refreshes with the same token cannot both succeed."""
        return await self._session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )

    async def add_reset_token(
        self, user: User, token_hash: str, expires_at: datetime
    ) -> PasswordResetToken:
        """A new link replaces any earlier unused one."""
        await self._session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
            .values(used_at=datetime.now(UTC))
        )
        token = PasswordResetToken(
            tenant_id=user.tenant_id, user_id=user.id, token_hash=token_hash, expires_at=expires_at
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_reset_token_for_update(self, token_hash: str) -> PasswordResetToken | None:
        return await self._session.scalar(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
            .with_for_update()
        )

    async def revoke_all_refresh_tokens(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
