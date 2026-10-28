from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models.analytics import AnalyticsEventType
from app.repositories.events import EventRepository


async def emit(
    session: AsyncSession,
    ctx: TenantContext,
    event: AnalyticsEventType,
    source: UUID | str,
    *,
    conversation_id: UUID | None = None,
    occurred_at: datetime | None = None,
    catalog_item_id: UUID | None = None,
) -> None:
    """Write within the caller's transaction; rollback and replay preserve event correctness."""
    await EventRepository(session, ctx).emit(
        event,
        str(source),
        conversation_id=conversation_id,
        occurred_at=occurred_at,
        catalog_item_id=catalog_item_id,
    )
