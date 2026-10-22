from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import DomainError, Unauthorized
from app.core.security import decode_token
from app.core.tenant import TenantContext
from app.repositories.identity import UserRepository

bearer = HTTPBearer(auto_error=False)


def settings_for(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def session_for(request: Request) -> AsyncIterator[AsyncSession]:
    factory = cast(async_sessionmaker[AsyncSession], request.app.state.sessions)
    async with factory() as session:
        yield session


Session = Annotated[AsyncSession, Depends(session_for)]
Config = Annotated[Settings, Depends(settings_for)]


async def tenant_context(
    settings: Config,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> TenantContext:
    if credentials is None:
        raise Unauthorized()
    claims = decode_token(settings, credentials.credentials, "access")
    ctx = TenantContext(claims.tenant_id, claims.sub)
    user = await UserRepository(session, ctx).get(claims.sub)
    if not user.is_active:
        raise Unauthorized()
    return TenantContext(user.tenant_id, user.id, user.role.value)


Context = Annotated[TenantContext, Depends(tenant_context)]


def require_owner(ctx: Context) -> TenantContext:
    if ctx.role != "owner":
        raise DomainError("Owner role required", 403)
    return ctx


Owner = Annotated[TenantContext, Depends(require_owner)]


def require_trace_reader(ctx: Context) -> TenantContext:
    if ctx.role not in {"owner", "admin"}:
        raise DomainError("Owner or admin role required", 403)
    return ctx


TraceReader = Annotated[TenantContext, Depends(require_trace_reader)]
