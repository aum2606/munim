from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.agents.quotation import QuotationAgent
from app.core.config import Settings
from app.core.errors import DomainError, NotFound
from app.core.tenant import TenantContext
from app.db.models.conversation import Message
from app.db.models.quote import Quote
from app.llm import LLMClient
from app.llm.types import ToolCall
from app.pricing.engine import price_line, quote_totals
from app.pricing.inr import format_inr
from app.pricing.quote_number import next_quote_number
from app.quotes.pdf import render_quote_pdf
from app.repositories.catalog import CatalogRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.identity import TenantRepository
from app.repositories.leads import LeadRepository
from app.repositories.pricing_rules import PricingRuleRepository
from app.repositories.quotes import QuoteRepository, QuoteSequenceRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.pricing import AddonRule, LineResult, PriceItem, Totals
from app.schemas.quotes import (
    QuotationInput,
    QuoteCandidate,
    QuoteLineInput,
    QuoteLineView,
    QuoteView,
    Seller,
)
from app.schemas.requirements import SlotUpdate


class QuoteService:
    def __init__(self, session: AsyncSession, ctx: TenantContext, config: Settings) -> None:
        self.session, self.ctx, self.config = session, ctx, config
        self.quotes = QuoteRepository(session, ctx)

    async def view(self, quote_id: UUID) -> QuoteView:
        quote = await self.quotes.get(quote_id)
        lines = [QuoteLineView.model_validate(line) for line in await self.quotes.lines(quote_id)]
        totals = Totals.model_validate(quote.pricing_snapshot)
        return QuoteView(
            id=quote.id,
            quote_number=quote.quote_number,
            conversation_id=quote.conversation_id,
            status=quote.status,
            version=quote.version,
            seller=Seller.model_validate(quote.seller),
            customer_label=quote.customer_label,
            customer_state=quote.customer_state,
            created_at=quote.created_at,
            valid_until=quote.valid_until,
            terms=quote.terms,
            lines=lines,
            totals=totals,
            display_total=format_inr(totals.total_paise),
            quote_discount_paise=totals.quote_discount_paise,
            display_amounts={
                key: format_inr(value)
                for key, value in totals.model_dump().items()
                if isinstance(value, int)
            },
            display_lines=[
                {
                    "unit_price": format_inr(line.unit_price_paise),
                    "addon": format_inr(line.addon_paise),
                    "discount": format_inr(line.discount_paise),
                    "taxable": format_inr(line.line_total_paise),
                }
                for line in lines
            ],
            approved_by=quote.approved_by,
            sent_at=quote.sent_at,
        )

    async def calculate(
        self, inputs: list[QuoteLineInput], customer_state: str | None, discount_paise: int = 0
    ) -> tuple[list[dict[str, Any]], Totals]:
        results: list[LineResult] = []
        snapshots: list[dict[str, Any]] = []
        for body in inputs:
            catalog = await CatalogRepository(self.session, self.ctx).by_sku(body.sku)
            if catalog is None:
                raise DomainError("Select an active catalogue SKU for each line")
            rules = await PricingRuleRepository(self.session, self.ctx).applicable(catalog)
            for key, value in body.options.items():
                is_default = value in catalog.attributes.get("default_" + key, "").split("|")
                is_priced = any(
                    isinstance(rule, AddonRule) and rule.option == key and rule.value == value
                    for rule in rules
                )
                if not (is_default or is_priced):
                    raise DomainError("An option needs an owner-configured price or default")
            result = price_line(
                PriceItem.model_validate(
                    {"base_price_paise": catalog.base_price_paise, "gst_rate": catalog.gst_rate}
                ),
                body.qty,
                body.options,
                rules,
                body.discount_paise,
            )
            results.append(result)
            snapshots.append(
                {
                    "catalog_item_id": catalog.id,
                    "sku": catalog.sku,
                    "description": catalog.name,
                    "qty": result.qty,
                    "unit": catalog.unit,
                    "unit_price_paise": result.unit_price_paise,
                    "addon_paise": result.addon_paise,
                    "discount_paise": result.discount_paise,
                    "gst_rate": catalog.gst_rate,
                    "hsn_sac": catalog.hsn_sac,
                    "line_total_paise": result.taxable_paise,
                    "needs_owner_pricing": False,
                    "options": body.options,
                }
            )
        tenant = await TenantRepository(self.session, self.ctx).get()
        return snapshots, quote_totals(results, tenant.state_code, customer_state, discount_paise)

    async def write_pdf(self, quote_id: UUID) -> str:
        quote = await self.quotes.get(quote_id)
        view = await self.view(quote_id)
        content = await run_in_threadpool(render_quote_pdf, view, Path(self.config.storage_dir))
        relative = (
            Path(str(self.ctx.tenant_id))
            / "quotes"
            / f"{quote.id}-v{quote.version}-{quote.status.value}.pdf"
        )
        path = Path(self.config.storage_dir) / relative

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)

        await run_in_threadpool(write)
        quote.pdf_path = str(relative)
        await self.session.flush()
        return str(relative)

    async def pdf(self, quote_id: UUID) -> bytes:
        quote = await self.quotes.get(quote_id)
        if not quote.pdf_path:
            raise NotFound()

        def read() -> bytes:
            root = Path(self.config.storage_dir).resolve()
            path = (root / str(quote.pdf_path)).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise NotFound()
            return path.read_bytes()

        return await run_in_threadpool(read)

    async def create_from_requirements(
        self, conversation_id: UUID, message_id: UUID, llm: LLMClient
    ) -> Quote:
        existing = await self.quotes.for_message(message_id)
        if existing:
            return existing
        conversation = await ConversationRepository(self.session, self.ctx).get(
            conversation_id, for_update=True
        )
        source = await ScopedRepository(self.session, self.ctx, Message).get(message_id)
        if source.conversation_id != conversation_id or not conversation.active_flow.get(
            "ready_for_quote"
        ):
            raise DomainError("Requirements are not complete")
        state = conversation.active_flow
        filled = state["filled"]
        lead = await LeadRepository(self.session, self.ctx).for_conversation(
            conversation_id, state["category"]
        )
        agent = QuotationAgent(llm)
        catalogs = [
            catalog
            for catalog in await agent.call_tool(
                "lookup_catalog", lambda: CatalogRepository(self.session, self.ctx).list()
            )
            if catalog.is_active
        ]
        proposals = await agent.run(
            self.ctx,
            QuotationInput(
                category=state["category"],
                requirements=[
                    SlotUpdate(key=key, value=str(value)) for key, value in filled.items()
                ],
                candidates=[
                    QuoteCandidate(
                        sku=catalog.sku,
                        name=catalog.name,
                        aliases=catalog.aliases,
                        unit=catalog.unit,
                        attributes=[
                            SlotUpdate(key=key, value=str(value))
                            for key, value in catalog.attributes.items()
                        ],
                    )
                    for catalog in catalogs
                ],
            ),
            message_id=message_id,
            tools_used=[ToolCall(name="lookup_catalog", arguments={"category": state["category"]})],
        )
        by_sku = {catalog.sku: catalog for catalog in catalogs}
        inputs: list[QuoteLineInput] = []
        unpriced = bool(proposals.unmapped_requirements) or not proposals.lines
        seen: set[str] = set()
        for proposal in proposals.lines:
            if proposal.sku not in by_sku or proposal.sku in seen:
                unpriced = True
                continue
            catalog = by_sku[proposal.sku]
            seen.add(catalog.sku)
            qty = Decimal(proposal.qty)
            expected = Decimal(str(filled.get("quantity", filled.get("days", 1))))
            pack_size = Decimal(str(catalog.attributes.get("pack_size", "1")))
            if not pack_size.is_finite() or pack_size <= 0 or expected / pack_size != qty:
                unpriced = True
                continue
            options = {option.key: option.value for option in proposal.options}
            # Copy all price-sensitive supplied options; the model cannot silently omit them.
            for key in (
                "size",
                "material",
                "sides",
                "colour",
                "finishing",
                "hours",
                "crew_size",
                "deliverables",
                "event_type",
                "brand",
                "specs",
                "delivery",
            ):
                if key in filled:
                    options[key] = str(filled[key])
            try:
                body = QuoteLineInput(sku=catalog.sku, qty=qty, options=options)
                await self.calculate([body], None)
                inputs.append(body)
            except DomainError:
                unpriced = True
        tenant_repo = TenantRepository(self.session, self.ctx)
        tenant, settings = await tenant_repo.get(), await tenant_repo.settings()
        if inputs:
            snapshots, totals = await agent.call_tool(
                "price_quote", lambda: self.calculate(inputs, None)
            )
        else:
            snapshots = []
            totals = quote_totals(
                [price_line(PriceItem(base_price_paise=0, gst_rate=0), Decimal(1), {}, [])],
                tenant.state_code,
                None,
            )
        if unpriced:
            snapshots.append(
                {
                    "catalog_item_id": None,
                    "sku": None,
                    "description": "Requirements need owner pricing",
                    "qty": Decimal(1),
                    "unit": "service",
                    "unit_price_paise": 0,
                    "addon_paise": 0,
                    "discount_paise": 0,
                    "gst_rate": 0,
                    "hsn_sac": "",
                    "line_total_paise": 0,
                    "needs_owner_pricing": True,
                    "options": {},
                }
            )
        quote = await self.quotes.create(
            lead_id=lead.id,
            conversation_id=conversation_id,
            source_message_id=message_id,
            quote_number=await next_quote_number(QuoteSequenceRepository(self.session, self.ctx)),
            seller=Seller(
                name=tenant.name,
                address=tenant.address or "",
                gstin=tenant.gstin or "",
                state_code=tenant.state_code,
                logo_path=tenant.logo_url,
            ).model_dump(),
            customer_label="Customer",
            customer_state=None,
            terms=settings.quote_terms,
            valid_until=datetime.now(UTC) + timedelta(days=settings.quote_validity_days),
            pricing_snapshot=totals.model_dump(mode="json"),
            **{
                key: value
                for key, value in totals.model_dump().items()
                if key not in {"taxable_paise", "tax_groups", "quote_discount_paise"}
            },
        )
        await self.quotes.replace_lines(quote.id, snapshots)
        await agent.call_tool("render_quote_pdf", lambda: self.write_pdf(quote.id))
        conversation.active_flow = {**state, "kind": "quote_pending", "quote_id": str(quote.id)}
        await llm.recorder.record(
            self.ctx,
            agent="quotation_tools",
            model="deterministic",
            request={"quote_id": str(quote.id)},
            output={"totals": totals.model_dump(mode="json")},
            tool_calls=[
                ToolCall(name="price_quote", arguments={"quote_id": str(quote.id)}).model_dump(),
                ToolCall(
                    name="render_quote_pdf", arguments={"quote_id": str(quote.id)}
                ).model_dump(),
            ],
            latency_ms=0,
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd_micros=0,
            status="success",
            error=None,
            message_id=message_id,
        )
        return quote
