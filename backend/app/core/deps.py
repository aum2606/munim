from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import Role, TenantContext
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.repositories.auth import AuthRepository

_bearer = HTTPBearer(auto_error=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request; commits on success, rolls back if anything raises."""
    async with request.app.state.sessionmaker() as session:
        yield session
        await session.commit()


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


# scope="function": the commit runs before the response is sent, so a client never sees a 2xx
# for work that failed to commit.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_tenant_context(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
    settings: SettingsDep,
) -> TenantContext:
    if creds is None:
        raise UnauthorizedError("Not authenticated")
    claims = decode_access_token(settings, creds.credentials)
    # Load the user on every request so deactivation and role changes apply immediately.
    user = await AuthRepository(session).get_user_by_id(claims.user_id)
    if user is None or not user.is_active or user.tenant_id != claims.tenant_id:
        raise UnauthorizedError("Invalid or expired token")
    return TenantContext(tenant_id=user.tenant_id, user_id=user.id, role=user.role)


CtxDep = Annotated[TenantContext, Depends(get_tenant_context, scope="function")]


async def require_owner(ctx: CtxDep) -> TenantContext:
    if ctx.role != Role.OWNER:
        raise ForbiddenError("Owner access required")
    return ctx


OwnerDep = Annotated[TenantContext, Depends(require_owner, scope="function")]
