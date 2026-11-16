import uuid

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import Channel, Lead, LeadEvent, LeadStage


class LeadRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    def _mine(self, *extra: ColumnElement[bool]) -> ColumnElement[bool]:
        return and_(Lead.tenant_id == self._ctx.tenant_id, *extra)

    async def for_conversation(self, conversation_id: uuid.UUID) -> Lead | None:
        return await self._session.scalar(
            select(Lead).where(self._mine(Lead.conversation_id == conversation_id))
        )

    async def get(self, lead_id: uuid.UUID) -> Lead | None:
        return await self._session.scalar(select(Lead).where(self._mine(Lead.id == lead_id)))

    async def add(
        self, *, customer_id: uuid.UUID, conversation_id: uuid.UUID, channel: Channel
    ) -> Lead:
        lead = Lead(
            tenant_id=self._ctx.tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            source_channel=channel,
            stage=LeadStage.NEW,
        )
        self._session.add(lead)
        await self._session.flush()
        return lead

    async def browse(self, stage: LeadStage | None = None, limit: int = 100) -> list[Lead]:
        query = select(Lead).where(self._mine())
        if stage:
            query = query.where(Lead.stage == stage)
        result = await self._session.scalars(query.order_by(Lead.score.desc()).limit(limit))
        return list(result)

    async def add_event(
        self,
        lead: Lead,
        event_type: str,
        *,
        actor: str,
        from_value: str | None = None,
        to_value: str | None = None,
        note: str | None = None,
    ) -> None:
        self._session.add(
            LeadEvent(
                tenant_id=self._ctx.tenant_id,
                lead_id=lead.id,
                event_type=event_type,
                from_value=from_value,
                to_value=to_value,
                actor=actor,
                note=note,
            )
        )
        await self._session.flush()

    async def events(self, lead_id: uuid.UUID) -> list[LeadEvent]:
        result = await self._session.scalars(
            select(LeadEvent)
            .where(LeadEvent.tenant_id == self._ctx.tenant_id, LeadEvent.lead_id == lead_id)
            .order_by(LeadEvent.created_at)
        )
        return list(result)
