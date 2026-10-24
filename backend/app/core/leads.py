from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.lead import LeadAgent
from app.core.tenant import TenantContext
from app.db.models import Customer, Message
from app.db.models.lead import LeadStage
from app.db.models.quote import QuoteStatus
from app.llm import LLMClient
from app.repositories.conversations import ConversationRepository
from app.repositories.identity import TenantRepository
from app.repositories.leads import LeadRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.leads import FollowupPolicy, LeadInput


def lead_score(phone: bool, complete: bool, quoted: bool, recent: bool, signal: int) -> int:
    # Base: contact 20 + completed requirements 30 + delivered quote 30 + recent 20.
    # Model buying signal is bounded to +/-20; clamp the final result to 0..100.
    return max(
        0,
        min(
            100, 20 * phone + 30 * complete + 30 * quoted + 20 * recent + max(-20, min(20, signal))
        ),
    )


class LeadService:
    def __init__(self, session: AsyncSession, ctx: TenantContext, llm: LLMClient) -> None:
        self.session, self.ctx, self.llm = session, ctx, llm

    async def update(self, message_id: UUID) -> None:
        message = await ScopedRepository(self.session, self.ctx, Message).get(message_id)
        conversations = ConversationRepository(self.session, self.ctx)
        conversation = await conversations.get(message.conversation_id, for_update=True)
        repository = LeadRepository(self.session, self.ctx)
        latest = await repository.latest_inbound(conversation.id)
        if latest is None or latest.id != message_id or latest.processed_at is None:
            return
        tenant = await TenantRepository(self.session, self.ctx).get()
        lead = await repository.for_conversation(conversation.id, tenant.business_type)
        if lead.last_scored_message_id == message_id:
            return
        history = await conversations.messages(conversation.id, 12)
        body = LeadInput(messages=[entry.content for entry in history])
        # Release row locks before the model call; background scoring must not delay chat.
        await self.session.commit()
        result = await LeadAgent(self.llm).run(self.ctx, body, message_id=message_id)
        conversation = await conversations.get(message.conversation_id, for_update=True)
        latest = await repository.latest_inbound(conversation.id)
        lead = await repository.for_conversation(conversation.id, tenant.business_type)
        if latest is None or latest.id != message_id or lead.last_scored_message_id == message_id:
            await self.session.commit()
            return
        customer = await ScopedRepository(self.session, self.ctx, Customer).get(
            conversation.customer_id
        )
        quote = await repository.latest_quote(conversation.id)
        quoted = quote is not None and quote.sent_at is not None
        complete = bool(conversation.active_flow.get("ready_for_quote")) or bool(quote)
        now = datetime.now(UTC)
        recent = bool(
            conversation.last_customer_msg_at
            and now - conversation.last_customer_msg_at < timedelta(days=7)
        )
        lead.score = lead_score(
            bool(customer.phone), complete, quoted, recent, result.buying_signal
        )
        lead.summary, lead.tags = result.summary, [tag[:60] for tag in result.tags]
        # Values are copied from a deterministic persisted quote, never from the model.
        lead.estimated_value_paise = quote.total_paise if quote else 0
        stage = LeadStage.ENGAGED
        if complete:
            stage = LeadStage.QUALIFIED
        if quoted:
            stage = LeadStage.QUOTED
        if latest.intent == "negotiation" and quoted:
            stage = LeadStage.NEGOTIATING
        if quote and quote.status == QuoteStatus.ACCEPTED:
            stage = LeadStage.WON
        if quote and quote.status == QuoteStatus.REJECTED:
            stage = LeadStage.LOST
        await repository.transition(lead, stage)
        policy = FollowupPolicy.model_validate(
            (await TenantRepository(self.session, self.ctx).settings()).followup_policy
        )
        if not lead.stage_override:
            lead.next_followup_at = (
                now + timedelta(days=policy.no_reply_days)
                if policy.enabled and lead.stage not in {LeadStage.WON, LeadStage.LOST}
                else None
            )
        lead.last_scored_message_id = message_id
        await self.session.commit()
