from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models.analytics import AnalyticsEvent, AnalyticsEventType


class EventRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def emit(
        self,
        event: AnalyticsEventType,
        source_key: str,
        *,
        occurred_at: datetime | None = None,
        conversation_id: UUID | None = None,
        catalog_item_id: UUID | None = None,
    ) -> None:
        from app.db.models import CatalogItem, Conversation
        from app.repositories.scoped import ScopedRepository

        if conversation_id is not None:
            await ScopedRepository(self.session, self.ctx, Conversation).get(conversation_id)
        if catalog_item_id is not None:
            await ScopedRepository(self.session, self.ctx, CatalogItem).get(catalog_item_id)
        # Allow-listed identifiers only: no customer text, contacts, secrets or model properties.
        properties = {
            key: str(value)
            for key, value in {
                "conversation_id": conversation_id,
                "catalog_item_id": catalog_item_id,
            }.items()
            if value is not None
        }
        await self.session.execute(
            insert(AnalyticsEvent)
            .values(
                tenant_id=self.ctx.tenant_id,
                event=event,
                source_key=source_key,
                occurred_at=occurred_at or datetime.now(UTC),
                properties=properties,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    AnalyticsEvent.tenant_id,
                    AnalyticsEvent.event,
                    AnalyticsEvent.source_key,
                ]
            )
        )
