from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.guardrails import check_prices
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models import Followup, LeadEvent, Message
from app.db.models.conversation import ConversationMode, ConversationStatus, Direction, SenderType
from app.db.models.lead import Lead, LeadStage
from app.db.models.quote import QuoteStatus
from app.repositories.conversations import ConversationRepository
from app.repositories.followups import FollowupRepository
from app.repositories.identity import TenantRepository
from app.repositories.leads import LeadRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.leads import FollowupPolicy

DRAFTS = {
    "no_reply": "Hello! Would you like any more help with your enquiry?",
    "quote_reminder": (
        "Hello! Your quotation is nearing its validity date. "
        "Would you like to discuss it with the team?"
    ),
    "reengage": (
        "Hello! Are you still interested in your earlier enquiry? The team is happy to help."
    ),
}


class FollowupService:
    def __init__(
        self, session: AsyncSession, ctx: TenantContext, config: Settings | None = None
    ) -> None:
        self.session, self.ctx = session, ctx
        self.config = config or Settings()
        self.repository = FollowupRepository(session, ctx)
        self.leads = LeadRepository(session, ctx)
        self.conversations = ConversationRepository(session, ctx)

    async def eligible(
        self, lead: Lead, now: datetime, policy: FollowupPolicy
    ) -> tuple[str, datetime] | None:
        conversation = await self.conversations.get(lead.conversation_id)
        last_business, last_customer = (
            conversation.last_business_msg_at,
            conversation.last_customer_msg_at,
        )
        if (
            not policy.enabled
            or conversation.status != ConversationStatus.OPEN
            or conversation.mode != ConversationMode.AI
            or lead.stage in {LeadStage.WON, LeadStage.LOST}
            or not last_business
            or not last_customer
            or last_customer > last_business
            or (
                lead.stage_override
                and lead.next_followup_at is not None
                and lead.next_followup_at > now
            )
        ):
            return None
        quote = await self.leads.latest_quote(conversation.id)
        if quote and quote.sent_at and quote.status in {QuoteStatus.SENT, QuoteStatus.VIEWED}:
            if now < quote.valid_until <= now + timedelta(days=policy.quote_reminder_days):
                return "quote_reminder", quote.valid_until
        if now - last_business >= timedelta(days=policy.reengage_days):
            return "reengage", last_business
        if lead.stage != LeadStage.DORMANT and now - last_business >= timedelta(
            days=policy.no_reply_days
        ):
            return "no_reply", last_business
        return None

    async def schedule(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        policy = FollowupPolicy.model_validate(
            (await TenantRepository(self.session, self.ctx).settings()).followup_policy
        )
        after: UUID | None = None
        count = 0
        while batch := await self.repository.candidates(after):
            for candidate in batch:
                await self.conversations.get(candidate.conversation_id, for_update=True)
                lead = await self.leads.get(candidate.id, for_update=True)
                eligible = await self.eligible(lead, now, policy)
                if eligible:
                    kind, source = eligible
                    check_prices(DRAFTS[kind], set())
                    await self.repository.schedule(
                        lead.id, kind, source, now, DRAFTS[kind], lead.source_channel != "web"
                    )
                    if kind == "reengage":
                        await self.leads.transition(lead, LeadStage.DORMANT)
                    if not lead.stage_override:
                        lead.next_followup_at = now
                    count += 1
                await self.session.commit()
            after = batch[-1].id
        # Invalidate owner-visible drafts when the customer replied or the workflow changed.
        for draft in await self.repository.pending():
            lead = await self.leads.get(draft.lead_id)
            eligible = await self.eligible(lead, now, policy)
            if eligible != (draft.kind, draft.source_at):
                draft.status = "cancelled"
        await self.session.commit()
        return count

    async def act(
        self, followup_id: UUID, approve: bool, template_id: UUID | None = None
    ) -> Followup:
        initial = await self.repository.get(followup_id)
        lead = await self.leads.get(initial.lead_id)
        conversation = await self.conversations.get(lead.conversation_id, for_update=True)
        draft = await self.repository.get(followup_id, for_update=True)
        if draft.status != "scheduled":
            return draft
        if not approve:
            draft.status = "cancelled"
        else:
            now = datetime.now(UTC)
            policy = FollowupPolicy.model_validate(
                (await TenantRepository(self.session, self.ctx).settings()).followup_policy
            )
            if await self.eligible(lead, now, policy) != (draft.kind, draft.source_at):
                draft.status = "skipped"
            elif conversation.channel not in {"web", "whatsapp"}:
                raise DomainError("This channel requires an approved template and adapter", 409)
            else:
                from app.channels.service import require_send

                template = None
                if conversation.channel == "whatsapp":
                    if template_id is None:
                        raise DomainError(
                            "Choose an approved WhatsApp template before approval", 409
                        )
                    template = await require_send(
                        self.session, self.ctx, self.config, conversation.id, template_id
                    )
                    if template is None:
                        raise DomainError("WhatsApp template is required", 409)
                    draft.draft_text = template.body_text
                check_prices(draft.draft_text, set())
                outbound = await ScopedRepository(self.session, self.ctx, Message).create(
                    conversation_id=conversation.id,
                    direction=Direction.OUT,
                    sender_type=SenderType.STAFF,
                    content=draft.draft_text,
                    external_id=f"followup:{draft.id}",
                    attachments=[],
                )
                from app.repositories.channels import ChannelRepository

                await ChannelRepository(self.session, self.ctx).queue(
                    outbound, template_id if template else None
                )
                conversation.last_business_msg_at = now
                draft.status = "sent"
                lead.next_followup_at = None
        await ScopedRepository(self.session, self.ctx, LeadEvent).create(
            lead_id=lead.id,
            event_type="followup",
            from_value="scheduled",
            to_value=draft.status,
            actor=str(self.ctx.user_id),
            note=draft.kind,
        )
        await self.session.commit()
        return draft
