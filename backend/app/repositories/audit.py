from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import AuditEvent, User
from app.db.models.audit import AuditAction


class AuditEntry(NamedTuple):
    id: str
    created_at: datetime
    action: str
    target: str | None
    actor: str | None  # the user's name; None for the system or a user since deleted


class AuditRepository:
    """Append and read only: there is deliberately no update or delete."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    async def record(self, action: AuditAction, target: str | None = None) -> None:
        self._session.add(
            AuditEvent(
                tenant_id=self._ctx.tenant_id,
                user_id=self._ctx.user_id,
                action=action.value,
                target=target[:80] if target else None,
            )
        )

    async def browse(self, limit: int = 100) -> list[AuditEntry]:
        rows = await self._session.execute(
            select(AuditEvent, User.name)
            .outerjoin(User, User.id == AuditEvent.user_id)
            .where(AuditEvent.tenant_id == self._ctx.tenant_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .limit(limit)
        )
        return [AuditEntry(str(e.id), e.created_at, e.action, e.target, name) for e, name in rows]
