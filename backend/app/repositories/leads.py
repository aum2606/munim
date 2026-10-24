from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import Message, Quote
from app.db.models.conversation import Direction
from app.db.models.lead import Lead, LeadEvent, LeadStage
from app.repositories.conversations import ConversationRepository
from app.repositories.identity import UserRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.leads import LeadPatch


class LeadRepository(ScopedRepository[Lead]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, Lead)

    async def for_conversation(self, conversation_id: UUID, category: str) -> Lead:
        conversation = await ConversationRepository(self.session, self.ctx).get(
            conversation_id, for_update=True
        )
        lead = (
            await self.session.scalars(
                select(Lead).where(
                    Lead.tenant_id == self.ctx.tenant_id,
                    Lead.conversation_id == conversation_id,
                )
            )
        ).one_or_none()
        if lead is None:
            lead = await self.create(
                customer_id=conversation.customer_id,
                conversation_id=conversation_id,
                category=category,
                source_channel=conversation.channel,
            )
        return lead

    async def filtered(
        self, stage: LeadStage | None = None, score_min: int = 0, followup_due: bool = False
    ) -> list[Lead]:
        statement = select(Lead).where(
            Lead.tenant_id == self.ctx.tenant_id, Lead.score >= score_min
        )
        if stage:
            statement = statement.where(Lead.stage == stage)
        if followup_due:
            statement = statement.where(Lead.next_followup_at <= datetime.now(UTC))
        return list(
            await self.session.scalars(statement.order_by(Lead.updated_at.desc()).limit(200))
        )

    async def events(self, lead_id: UUID) -> list[LeadEvent]:
        await self.get(lead_id)
        return list(
            await self.session.scalars(
                select(LeadEvent)
                .where(LeadEvent.tenant_id == self.ctx.tenant_id, LeadEvent.lead_id == lead_id)
                .order_by(LeadEvent.created_at, LeadEvent.id)
                .limit(200)
            )
        )

    async def transition(self, lead: Lead, stage: LeadStage, *, manual: bool = False) -> None:
        if not manual:
            if lead.stage_override or lead.stage in {LeadStage.WON, LeadStage.LOST}:
                return
            order = [
                LeadStage.NEW,
                LeadStage.ENGAGED,
                LeadStage.QUALIFIED,
                LeadStage.QUOTED,
                LeadStage.NEGOTIATING,
            ]
            if (
                lead.stage in order
                and stage in order
                and order.index(stage) < order.index(lead.stage)
            ):
                return
        previous = lead.stage
        if manual:
            lead.stage_override = True
        if previous != stage:
            lead.stage = stage
            await ScopedRepository(self.session, self.ctx, LeadEvent).create(
                lead_id=lead.id,
                event_type="stage",
                from_value=previous.value,
                to_value=stage.value,
                actor=str(self.ctx.user_id) if manual else "ai",
                note="Manual override" if manual else "Workflow evidence",
            )

    async def patch(self, lead_id: UUID, body: LeadPatch) -> Lead:
        # All lifecycle writers lock conversation before lead to serialize with message processing.
        existing = await self.get(lead_id)
        await ConversationRepository(self.session, self.ctx).get(
            existing.conversation_id, for_update=True
        )
        lead = await self.get(lead_id, for_update=True)
        if body.assigned_to is not None:
            await UserRepository(self.session, self.ctx).get(body.assigned_to)
        if body.next_followup_at and body.next_followup_at.tzinfo is None:
            from app.core.errors import DomainError

            raise DomainError("Follow-up timestamp must include timezone")
        before = LeadPatch.model_validate(
            {key: getattr(lead, key) for key in body.model_fields_set}
        ).model_dump_json(exclude_unset=True)
        if body.stage is not None:
            await self.transition(lead, body.stage, manual=True)
        for key in body.model_fields_set - {"stage"}:
            if key == "stage_override" and body.stage is not None:
                continue
            value = getattr(body, key)
            if key == "stage_override" and value is None:
                continue
            setattr(lead, key, value)
        await ScopedRepository(self.session, self.ctx, LeadEvent).create(
            lead_id=lead.id,
            event_type="manual_update",
            from_value=before,
            to_value=body.model_dump_json(exclude_unset=True),
            actor=str(self.ctx.user_id),
            note="Staff update",
        )
        await self.session.flush()
        return lead

    async def latest_quote(self, conversation_id: UUID) -> Quote | None:
        await ConversationRepository(self.session, self.ctx).get(conversation_id)
        return (
            await self.session.scalars(
                select(Quote)
                .where(
                    Quote.tenant_id == self.ctx.tenant_id, Quote.conversation_id == conversation_id
                )
                .order_by(Quote.created_at.desc())
                .limit(1)
            )
        ).first()

    async def latest_inbound(self, conversation_id: UUID) -> Message | None:
        await ConversationRepository(self.session, self.ctx).get(conversation_id)
        return (
            await self.session.scalars(
                select(Message)
                .where(
                    Message.tenant_id == self.ctx.tenant_id,
                    Message.conversation_id == conversation_id,
                    Message.direction == Direction.IN,
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
        ).first()
