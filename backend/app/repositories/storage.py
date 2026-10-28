from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext

BACKUP_LOCK = 6406001


async def protect_storage_write(session: AsyncSession, ctx: TenantContext) -> None:
    """Coordinate file writers with the backup snapshot barrier."""
    # Infrastructure-only global coordination; no cross-tenant data is queried or returned.
    await session.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": BACKUP_LOCK})
