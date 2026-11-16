"""Creating, editing, approving and delivering quotations.

Every amount here comes from app.pricing. A model proposes WHICH catalogue items and how many;
this code decides what they cost. A quote reaches a customer only after an owner approves it.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import ConflictError, FileRejectedError, NotFoundError
from app.db.models import Direction, Quote, QuoteItem, QuoteStatus, SenderType
from app.ingestion.uploads import read_upload, save_upload
from app.orchestrator.leads import sync_lead
from app.orchestrator.messages import quote_sent_message
from app.pricing.engine import (
    LineInput,
    PricedLine,
    Totals,
    line_amount,
    price_line,
    quote_totals,
)
from app.pricing.inr import format_inr
from app.quotes.pdf import PdfLine, QuotePdf, render_quote_pdf
from app.repositories.catalog import CatalogRepository
from app.repositories.chat import ChatRepository
from app.repositories.leads import LeadRepository
from app.repositories.pricing_rules import PricingRuleRepository
from app.repositories.quotes import QuoteRepository
from app.repositories.tenant import TenantRepository
from app.services.pricing_rules import build_rules

IST = ZoneInfo("Asia/Kolkata")
# "per 100", "per 100 pcs": the price is for that many pieces. "per 2 days" is NOT a pack size.
_PACK = re.compile(
    r"^\s*per\s+(\d+)\s*(?:pcs?|pieces?|nos?\.?|units?|sheets?|copies|cards?)?\s*$", re.IGNORECASE
)
_THREE_PLACES = Decimal("0.001")
_DEFAULT_GST = 18  # used for a line the owner still has to price
MAX_QUANTITY = Decimal(10_000_000)


@dataclass(frozen=True)
class ProposedLine:
    """What a model (or the owner) wants on the quote. No prices: those come from the engine."""

    description: str
    item_id: uuid.UUID | None  # None: nothing in the catalogue matches, the owner must price it
    quantity: Decimal
    width: Decimal | None = None
    height: Decimal | None = None
    addon_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class LineEdit:
    item_id: uuid.UUID
    qty: Decimal | None = None
    unit_price_paise: int | None = None
    discount_paise: int | None = None


@dataclass(frozen=True)
class QuoteView:
    quote: Quote
    items: list[QuoteItem]
    totals: Totals


def pack_size(unit: str) -> Decimal:
    """'per 100' means the price is for 100 pieces."""
    match = _PACK.search(unit)
    return Decimal(match[1]) if match else Decimal(1)


def billable_qty(
    unit: str, quantity: Decimal, width: Decimal | None, height: Decimal | None
) -> Decimal | None:
    """How many priced units the customer's quantity is. None if the size is needed but missing.
    Done here, in Decimal, so a model never multiplies anything."""
    if not 0 < quantity <= MAX_QUANTITY:
        return None
    if "sq" in unit.lower():
        if width is None or height is None or width <= 0 or height <= 0:
            return None
        amount = quantity * width * height
    else:
        amount = quantity / pack_size(unit)
    return amount.quantize(_THREE_PLACES, rounding=ROUND_HALF_UP)


def _priced(item: QuoteItem) -> PricedLine:
    return PricedLine(
        item.description,
        item.unit,
        item.qty,
        item.unit_price_paise,
        item.discount_paise,
        item.gst_rate,
        item.hsn_sac,
        item.catalog_item_id,
        item.line_total_paise,
    )


class QuoteService:
    def __init__(self, session: AsyncSession, ctx: TenantContext, settings: Settings) -> None:
        self._session = session
        self._ctx = ctx
        self._settings = settings
        self._quotes = QuoteRepository(session, ctx)
        self._tenant = TenantRepository(session, ctx)

    # --- creating -----------------------------------------------------------------------

    async def create(
        self, lead_id: uuid.UUID, proposed: list[ProposedLine]
    ) -> tuple[Quote, list[str]]:
        """Price the proposed lines and save a quote that waits for owner approval.

        Returns the quote and any rule problems found (a minimum order not met, an unknown
        add-on). Lines that cannot be priced are kept at zero and flagged for the owner.
        """
        catalog = CatalogRepository(self._session, self._ctx)
        rules_repo = PricingRuleRepository(self._session, self._ctx)
        lines: list[PricedLine] = []
        flagged: list[bool] = []
        notes: list[str] = []
        for line in proposed:
            item = await catalog.get(line.item_id) if line.item_id else None
            qty = billable_qty(item.unit, line.quantity, line.width, line.height) if item else None
            if item is None or not item.is_active or qty is None:
                lines.append(self._unpriced(line.description))
                flagged.append(True)
                continue
            result = price_line(
                LineInput(
                    description=item.name,
                    unit=item.unit,
                    base_price_paise=item.base_price_paise,
                    gst_rate=item.gst_rate,
                    qty=qty,
                    hsn_sac=item.hsn_sac,
                    catalog_item_id=item.id,
                    addon_codes=line.addon_codes,
                ),
                build_rules(await rules_repo.applying_to(item)),
            )
            notes += [f"{item.name}: {v}" for v in result.violations]
            lines += result.lines
            flagged += [False] * len(result.lines)

        tenant = await self._tenant.get()
        settings = await self._tenant.get_settings()
        today = datetime.now(IST).date()
        valid_days = settings.quote_validity_days if settings else 7
        totals = quote_totals(lines, tenant.state_code if tenant else None, None)
        quote = await self._quotes.add(
            lead_id=lead_id,
            number=await self._quotes.next_number(today),
            totals=totals,
            valid_until=today + timedelta(days=valid_days),
            buyer_state_code=None,
        )
        await self._quotes.replace_items(quote.id, self._rows(quote.id, lines, flagged))
        return quote, notes

    @staticmethod
    def _unpriced(description: str) -> PricedLine:
        return PricedLine(
            f"{description} (price to be confirmed)"[:300],
            "each",
            Decimal(1),
            0,
            0,
            _DEFAULT_GST,
            None,
            None,
            0,
        )

    def _rows(
        self, quote_id: uuid.UUID, lines: list[PricedLine], flagged: list[bool]
    ) -> list[QuoteItem]:
        return [
            QuoteItem(
                tenant_id=self._ctx.tenant_id,
                quote_id=quote_id,
                position=position,
                catalog_item_id=line.catalog_item_id,
                description=line.description,
                qty=line.qty,
                unit=line.unit,
                unit_price_paise=line.unit_price_paise,
                discount_paise=line.discount_paise,
                gst_rate=line.gst_rate,
                hsn_sac=line.hsn_sac,
                line_total_paise=line.line_total_paise,
                needs_owner_pricing=needs,
            )
            for position, (line, needs) in enumerate(zip(lines, flagged, strict=True))
        ]

    # --- reading and editing --------------------------------------------------------------

    async def view(self, quote_id: uuid.UUID) -> QuoteView:
        quote = await self._quotes.get(quote_id)
        if quote is None:
            raise NotFoundError("Quote not found")
        items = await self._quotes.items(quote_id)
        tenant = await self._tenant.get()
        totals = quote_totals(
            [_priced(i) for i in items],
            tenant.state_code if tenant else None,
            quote.buyer_state_code,
        )
        return QuoteView(quote, items, totals)

    async def update(
        self,
        quote_id: uuid.UUID,
        edits: list[LineEdit],
        buyer_state_code: str | None,
        *,
        set_buyer_state: bool,
    ) -> QuoteView:
        """Owner edits before approval: quantity, unit price, discount, and the buyer's state.
        Line totals and taxes are recomputed by the engine, never taken from the request."""
        view = await self.view(quote_id)
        if view.quote.status != QuoteStatus.PENDING_APPROVAL:
            raise ConflictError("Only a quote waiting for approval can be edited")
        by_id = {i.id: i for i in view.items}
        for edit in edits:
            item = by_id.get(edit.item_id)
            if item is None:
                raise NotFoundError("Quote line not found")
            qty = item.qty if edit.qty is None else edit.qty
            price = (
                item.unit_price_paise if edit.unit_price_paise is None else edit.unit_price_paise
            )
            discount = item.discount_paise if edit.discount_paise is None else edit.discount_paise
            try:
                item.line_total_paise = line_amount(qty, price, discount)
            except ValueError as exc:
                raise FileRejectedError(str(exc)) from exc
            item.qty, item.unit_price_paise, item.discount_paise = qty, price, discount
            if edit.unit_price_paise is not None:
                item.needs_owner_pricing = False  # the owner has now priced it
        if set_buyer_state:
            view.quote.buyer_state_code = buyer_state_code
        await self._session.flush()
        refreshed = await self.view(quote_id)
        for column, value in QuoteRepository.total_columns(refreshed.totals).items():
            setattr(refreshed.quote, column, value)
        return refreshed

    # --- approving and delivering ---------------------------------------------------------

    async def pdf(self, quote_id: uuid.UUID) -> bytes:
        view = await self.view(quote_id)
        if view.quote.pdf_path:  # a sent quote is served exactly as the customer received it
            return read_upload(self._settings.storage_dir, view.quote.pdf_path)
        return await self._render(view)

    async def _render(self, view: QuoteView) -> bytes:
        tenant = await self._tenant.get()
        tenant_settings = await self._tenant.get_settings()
        lead = await LeadRepository(self._session, self._ctx).get(view.quote.lead_id)
        customer = None
        if lead is not None:
            customer = await ChatRepository(self._session, self._ctx).get_customer(lead.customer_id)
        if tenant is None:
            raise NotFoundError("Business not found")
        return render_quote_pdf(
            QuotePdf(
                seller_name=tenant.name,
                seller_gstin=tenant.gstin,
                seller_address=tenant.address,
                seller_phone=tenant.phone,
                seller_state=tenant.state_code,
                buyer_name=customer.name if customer else None,
                buyer_phone=customer.phone if customer else None,
                buyer_state=view.quote.buyer_state_code,
                quote_number=view.quote.quote_number,
                issued_on=view.quote.created_at.astimezone(IST).date(),
                valid_until=view.quote.valid_until,
                lines=[
                    PdfLine(
                        i.description,
                        i.hsn_sac,
                        i.qty,
                        i.unit,
                        i.unit_price_paise,
                        i.discount_paise,
                        i.gst_rate,
                        i.line_total_paise,
                    )
                    for i in view.items
                ],
                totals=view.totals,
                terms=tenant_settings.quote_terms if tenant_settings else None,
            )
        )

    async def approve(self, quote_id: uuid.UUID) -> QuoteView:
        """The owner approves: freeze the PDF, send the customer a message with the total."""
        view = await self.view(quote_id)
        quote = view.quote
        if quote.status != QuoteStatus.PENDING_APPROVAL:
            raise ConflictError("This quote is not waiting for approval")
        if not view.items or any(i.needs_owner_pricing for i in view.items):
            raise ConflictError("Price every line before approving")
        if quote.valid_until < datetime.now(IST).date():
            raise ConflictError("This quote has expired: ask for a new one")

        quote.pdf_path = save_upload(
            self._settings.storage_dir, self._ctx.tenant_id, await self._render(view), "pdf"
        )
        quote.status = QuoteStatus.SENT
        quote.approved_by = self._ctx.user_id
        quote.sent_at = datetime.now(UTC)

        chat = ChatRepository(self._session, self._ctx)
        leads = LeadRepository(self._session, self._ctx)
        lead = await leads.get(quote.lead_id)
        if lead is not None:
            conversation = await chat.get_conversation(lead.conversation_id)
            if conversation is not None:
                language = await chat.last_language(conversation.id) or "en"
                await chat.add_message(
                    conversation,
                    direction=Direction.OUT,
                    sender_type=SenderType.STAFF,
                    content=quote_sent_message(
                        language,
                        quote.quote_number,
                        format_inr(quote.total_paise),
                        f"{quote.valid_until:%d %b %Y}",
                    ),
                    language=language,
                    quote_id=quote.id,
                )
                await sync_lead(self._session, self._ctx, conversation)
                await leads.add_event(
                    lead, "quote_sent", actor=str(self._ctx.user_id), note=quote.quote_number
                )
        return view

    async def reject(self, quote_id: uuid.UUID) -> QuoteView:
        view = await self.view(quote_id)
        if view.quote.status != QuoteStatus.PENDING_APPROVAL:
            raise ConflictError("Only a quote waiting for approval can be rejected")
        view.quote.status = QuoteStatus.REJECTED
        await self._note(view.quote, "quote_rejected")
        return view

    async def mark_accepted(self, quote_id: uuid.UUID) -> QuoteView:
        """The customer said yes. This is what wins the lead."""
        view = await self.view(quote_id)
        if view.quote.status != QuoteStatus.SENT:
            raise ConflictError("Only a sent quote can be accepted")
        view.quote.status = QuoteStatus.ACCEPTED
        await self._note(view.quote, "quote_accepted")
        lead = await LeadRepository(self._session, self._ctx).get(view.quote.lead_id)
        if lead is not None:
            conversation = await ChatRepository(self._session, self._ctx).get_conversation(
                lead.conversation_id
            )
            if conversation is not None:
                await sync_lead(self._session, self._ctx, conversation)
        return view

    async def _note(self, quote: Quote, event: str) -> None:
        leads = LeadRepository(self._session, self._ctx)
        lead = await leads.get(quote.lead_id)
        if lead is not None:
            await leads.add_event(
                lead, event, actor=str(self._ctx.user_id), note=quote.quote_number
            )
