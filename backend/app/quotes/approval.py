from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.guardrails import check_reply
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models.conversation import (
    ConversationMode,
    ConversationStatus,
    Direction,
    Message,
    SenderType,
)
from app.db.models.lead import Lead, LeadStage
from app.db.models.quote import Quote, QuoteStatus
from app.pricing.inr import format_inr
from app.quotes.pdf import quote_allowed_prices
from app.quotes.service import QuoteService
from app.repositories.conversations import ConversationRepository
from app.repositories.identity import TenantRepository
from app.repositories.quotes import QuoteRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.quotes import QuoteEdit, Seller


class QuoteApproval:
    def __init__(self, session: AsyncSession, ctx: TenantContext, config: Settings) -> None:
        self.session, self.ctx, self.config = session, ctx, config
        self.quotes = QuoteRepository(session, ctx)
        self.service = QuoteService(session, ctx, config)

    @staticmethod
    def check_version(quote: Quote, expected: int) -> None:
        if quote.version != expected:
            raise DomainError("This quote changed. Reload it before continuing.", 409)

    async def edit(self, quote_id: UUID, body: QuoteEdit) -> Quote:
        quote = await self.quotes.get(quote_id, for_update=True)
        self.check_version(quote, body.expected_version)
        if quote.status != QuoteStatus.PENDING:
            raise DomainError("Only pending quotes can be edited", 409)
        snapshots, totals = await self.service.calculate(
            body.lines, body.customer_state, body.discount_paise
        )
        await self.quotes.replace_lines(quote.id, snapshots)
        tenant_repo = TenantRepository(self.session, self.ctx)
        tenant, settings = await tenant_repo.get(), await tenant_repo.settings()
        quote.seller = Seller(
            name=tenant.name,
            address=tenant.address or "",
            gstin=tenant.gstin or "",
            state_code=tenant.state_code,
            logo_path=tenant.logo_url,
        ).model_dump()
        quote.terms = settings.quote_terms
        quote.valid_until = datetime.now(UTC) + timedelta(days=settings.quote_validity_days)
        quote.customer_state = body.customer_state
        quote.pricing_snapshot = totals.model_dump(mode="json")
        for key, value in totals.model_dump().items():
            if key not in {"taxable_paise", "tax_groups", "quote_discount_paise"}:
                setattr(quote, key, value)
        quote.version += 1
        await self.service.write_pdf(quote.id)
        return quote

    async def send(
        self, quote_id: UUID, expected_version: int, *, automated: bool = False
    ) -> Quote:
        quote = await self.quotes.get(quote_id, for_update=True)
        self.check_version(quote, expected_version)
        if quote.status in {QuoteStatus.SENT, QuoteStatus.VIEWED, QuoteStatus.ACCEPTED}:
            return quote
        if quote.status != QuoteStatus.PENDING or quote.valid_until <= datetime.now(UTC):
            raise DomainError("This quote cannot be sent or has expired", 409)
        lines = await self.quotes.lines(quote.id)
        if not lines or any(line.needs_owner_pricing for line in lines):
            raise DomainError("Resolve every owner-pricing line before sending", 409)
        if any(line.gst_rate for line in lines) and not (
            quote.seller.get("gstin") and quote.seller.get("state_code")
        ):
            raise DomainError(
                "Set GSTIN and supplier state, then save a revised quote before sending", 409
            )
        conversation = await ConversationRepository(self.session, self.ctx).get(
            quote.conversation_id, for_update=True
        )
        settings = await TenantRepository(self.session, self.ctx).settings()
        if conversation.channel not in {"web", "whatsapp"}:
            raise DomainError("This channel does not support quotation delivery yet", 409)
        from app.channels.service import require_send

        await require_send(self.session, self.ctx, self.config, conversation.id)
        if automated:
            if not settings.auto_send_quotes or quote.total_paise >= settings.auto_send_limit_paise:
                raise DomainError("Quote does not meet the auto-send policy", 409)
            if (
                conversation.mode != ConversationMode.AI
                or conversation.status != ConversationStatus.OPEN
            ):
                raise DomainError("Auto-send requires an open AI conversation", 409)
        elif self.ctx.role != "owner" or self.ctx.user_id is None:
            raise DomainError("Owner approval is required", 403)
        quote.approved_by = None if automated else self.ctx.user_id
        quote.status = QuoteStatus.SENT
        quote.sent_at = datetime.now(UTC)
        await self.service.write_pdf(quote.id)
        view = await self.service.view(quote.id)
        valid_until = quote.valid_until.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
        text = (
            f"Your quotation {quote.quote_number} is ready. "
            f"Total: {format_inr(quote.total_paise)}. "
            f"Valid until {valid_until}. Download the PDF below."
        )
        check_reply(text, quote_allowed_prices(view), [text], settings.max_auto_discount_pct)
        outbound = await ScopedRepository(self.session, self.ctx, Message).create(
            conversation_id=quote.conversation_id,
            direction=Direction.OUT,
            sender_type=SenderType.SYSTEM,
            content=text,
            content_type="document",
            external_id=f"quote:{quote.id}:v{quote.version}",
            attachments=[
                {
                    "quote_id": str(quote.id),
                    "quote_number": quote.quote_number,
                    "filename": "quotation.pdf",
                    "automated": automated,
                }
            ],
        )
        from app.repositories.channels import ChannelRepository

        await ChannelRepository(self.session, self.ctx).queue(outbound)
        conversation.last_business_msg_at = quote.sent_at
        lead = await ScopedRepository(self.session, self.ctx, Lead).get(quote.lead_id)
        from app.repositories.leads import LeadRepository

        await LeadRepository(self.session, self.ctx).transition(lead, LeadStage.QUOTED)
        lead.estimated_value_paise = quote.total_paise
        await self.session.flush()
        return quote

    async def mark(self, quote_id: UUID, expected_version: int, status: QuoteStatus) -> Quote:
        quote = await self.quotes.get(quote_id, for_update=True)
        self.check_version(quote, expected_version)
        if quote.status != status:
            if quote.status not in {QuoteStatus.SENT, QuoteStatus.VIEWED}:
                raise DomainError("Only delivered quotes can be accepted or rejected", 409)
            quote.status = status
            from app.repositories.leads import LeadRepository

            repository = LeadRepository(self.session, self.ctx)
            await ConversationRepository(self.session, self.ctx).get(
                quote.conversation_id, for_update=True
            )
            lead = await repository.get(quote.lead_id, for_update=True)
            await repository.transition(
                lead, LeadStage.WON if status == QuoteStatus.ACCEPTED else LeadStage.LOST
            )
        await self.session.flush()
        return quote
