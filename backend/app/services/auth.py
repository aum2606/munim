from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, ForbiddenError, UnauthorizedError
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.db.models import User
from app.repositories.auth import AuthRepository
from app.schemas.auth import RegisterRequest

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
_BAD_LOGIN = "Invalid email or password"


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str  # raw; goes into an httpOnly cookie, only its hash is stored
    expires_in: int


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._repo = AuthRepository(session)

    async def register(self, data: RegisterRequest) -> IssuedTokens:
        if not self._settings.allow_registration:
            raise ForbiddenError("Registration is disabled")
        if await self._repo.get_user_by_email(data.email):
            raise ConflictError("An account with this email already exists")
        try:
            owner = await self._repo.create_tenant_with_owner(
                business_name=data.business_name,
                business_type=data.business_type,
                owner_name=data.name,
                email=data.email,
                password_hash=hash_password(data.password),
            )
        except IntegrityError as exc:  # lost a race with a concurrent registration
            raise ConflictError("An account with this email already exists") from exc
        return await self._issue(owner)

    async def login(self, email: str, password: str) -> IssuedTokens:
        now = datetime.now(UTC)
        user = await self._repo.get_user_by_email(email)
        locked = user is not None and user.locked_until is not None and user.locked_until > now
        # Always verify something so response time does not reveal whether the email exists.
        password_ok = verify_password(
            user.password_hash if user else dummy_password_hash(), password
        )
        if user is None or locked or not user.is_active or not password_ok:
            if user is not None and user.is_active and not locked:
                user.failed_login_count += 1
                if user.failed_login_count >= MAX_FAILED_LOGINS:
                    user.locked_until = now + LOCKOUT
                    user.failed_login_count = 0
                await self._session.commit()  # persist the counter even though we raise
            raise UnauthorizedError(_BAD_LOGIN)  # same message for every failure
        user.failed_login_count = 0
        user.locked_until = None
        return await self._issue(user)

    async def refresh(self, raw_token: str) -> IssuedTokens:
        now = datetime.now(UTC)
        token = await self._repo.get_refresh_token_for_update(hash_refresh_token(raw_token))
        if token is None:
            raise UnauthorizedError("Invalid session")
        if token.revoked_at is not None:
            # A rotated-out token is being replayed: assume theft and end every session.
            await self._repo.revoke_all_refresh_tokens(token.user_id)
            await self._session.commit()
            raise UnauthorizedError("Invalid session")
        user = await self._repo.get_user_by_id(token.user_id)
        if token.expires_at <= now or user is None or not user.is_active:
            raise UnauthorizedError("Invalid session")
        token.revoked_at = now  # rotation: each refresh token works exactly once
        return await self._issue(user)

    async def logout(self, raw_token: str) -> None:
        token = await self._repo.get_refresh_token_for_update(hash_refresh_token(raw_token))
        if token is not None and token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)

    async def _issue(self, user: User) -> IssuedTokens:
        raw, token_hash = new_refresh_token()
        expires = datetime.now(UTC) + timedelta(days=self._settings.refresh_token_days)
        await self._repo.add_refresh_token(user, token_hash, expires)
        return IssuedTokens(
            access_token=create_access_token(self._settings, user.id, user.tenant_id),
            refresh_token=raw,
            expires_in=self._settings.access_token_minutes * 60,
        )
