"""Forgot-password: ask for a link, then set a new password with it."""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import ConflictError
from app.core.security import hash_password, hash_refresh_token, new_refresh_token
from app.jobs.queue import enqueue
from app.repositories.auth import AuthRepository
from app.services.mailer import Mailer

log = structlog.get_logger()
BAD_LINK = "This reset link is invalid or has expired"


async def request_reset(session: AsyncSession, settings: Settings, email: str) -> None:
    """Queue the email. The caller answers the same whether or not the address has an account,
    and the work happens in the worker so the response time says nothing either."""
    if not settings.mail_ready:
        log.warning("password_reset_unavailable", reason="smtp_not_configured")
        return
    user = await AuthRepository(session).get_user_by_email(email)
    if user is not None and user.is_active:
        await enqueue(
            session,
            TenantContext.system(user.tenant_id),
            "send_password_reset",
            {"user_id": str(user.id)},
            max_attempts=3,
        )


async def send_reset_email(
    session: AsyncSession, settings: Settings, mailer: Mailer, user_id: uuid.UUID
) -> None:
    """Worker side: make a one-time link and mail it. Only the link's hash is stored."""
    repo = AuthRepository(session)
    user = await repo.get_user_by_id(user_id)
    if user is None or not user.is_active:
        return
    raw, token_hash = new_refresh_token()
    minutes = settings.password_reset_minutes
    await repo.add_reset_token(user, token_hash, datetime.now(UTC) + timedelta(minutes=minutes))
    link = f"{settings.public_url.rstrip('/')}/reset-password?token={raw}"
    await mailer.send(
        user.email,
        "Reset your Munim password",
        "Someone asked to reset the password for this account.\n\n"
        f"Open this link within {minutes} minutes to choose a new one:\n{link}\n\n"
        "If it was not you, ignore this email: your password has not changed.",
    )


async def reset_password(session: AsyncSession, raw_token: str, new_password: str) -> None:
    repo = AuthRepository(session)
    token = await repo.get_reset_token_for_update(hash_refresh_token(raw_token))
    now = datetime.now(UTC)
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise ConflictError(BAD_LINK)
    user = await repo.get_user_by_id(token.user_id)
    if user is None or not user.is_active:
        raise ConflictError(BAD_LINK)
    user.password_hash = hash_password(new_password)
    user.failed_login_count, user.locked_until = 0, None  # the owner is back: lift any lockout
    token.used_at = now
    await repo.revoke_all_refresh_tokens(user.id)  # whoever had the old password is signed out
