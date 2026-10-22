from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import DomainError, Unauthorized
from app.core.security import (
    DUMMY_HASH,
    decode_token,
    hash_password,
    issue_token,
    token_hash,
    verify_password,
)
from app.core.tenant import TenantContext
from app.db.models import User
from app.repositories.identity import IdentityRepository, UserRepository
from app.repositories.sessions import SessionRepository
from app.schemas.auth import LoginInput, RegisterInput, Tokens


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings

    async def tokens(self, user: User) -> Tokens:
        access, _ = issue_token(self.settings, user.id, user.tenant_id, "access")
        refresh, expiry = issue_token(self.settings, user.id, user.tenant_id, "refresh")
        await SessionRepository(self.session, TenantContext(user.tenant_id)).create(
            user.id, token_hash(refresh), expiry
        )
        return Tokens(access_token=access, refresh_token=refresh)

    async def register(self, request: RegisterInput) -> Tokens:
        try:
            hashed = await run_in_threadpool(hash_password, request.password)
            user = await IdentityRepository(self.session).register(
                request.business_name,
                request.business_type,
                str(request.email).lower(),
                request.name,
                hashed,
            )
            tokens = await self.tokens(user)
            await self.session.commit()
            return tokens
        except IntegrityError as error:
            await self.session.rollback()
            raise DomainError("Unable to register with these details", 409) from error

    async def login(self, request: LoginInput) -> Tokens:
        user = await IdentityRepository(self.session).discover_login(str(request.email).lower())
        # A fixed dummy hash keeps unknown-email verification on the Argon2 path.
        hashed = user.password_hash if user else DUMMY_HASH
        valid = await run_in_threadpool(verify_password, request.password, hashed)
        if not user or not valid or not user.is_active:
            raise Unauthorized()
        tokens = await self.tokens(user)
        await self.session.commit()
        return tokens

    async def refresh(self, token: str) -> Tokens:
        claims = decode_token(self.settings, token, "refresh")
        ctx = TenantContext(claims.tenant_id)
        user_id = await SessionRepository(self.session, ctx).consume(
            token_hash(token), datetime.now(UTC)
        )
        user = await UserRepository(self.session, ctx).get(user_id)
        if not user.is_active or user.id != claims.sub:
            raise Unauthorized()
        tokens = await self.tokens(user)
        await self.session.commit()
        return tokens

    async def logout(self, token: str) -> None:
        claims = decode_token(self.settings, token, "refresh")
        await SessionRepository(self.session, TenantContext(claims.tenant_id)).revoke(
            token_hash(token)
        )
        await self.session.commit()
