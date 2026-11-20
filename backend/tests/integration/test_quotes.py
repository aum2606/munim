"""Quote conversations end to end (scripted models), and the quote service."""

import asyncio
import io
import json
import uuid
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import ConflictError, FileRejectedError, NotFoundError
from app.db.models import (
    Channel,
    ConversationMode,
    Direction,
    LeadStage,
    Message,
    Quote,
    QuoteStatus,
    SenderType,
)
from app.db.session import SessionMaker
from app.jobs.handlers import build_handlers
from app.llm.embedder import FakeEmbedder
from app.llm.fake import FakeLLM
from app.orchestrator.leads import sync_lead
from app.orchestrator.messages import canned
from app.orchestrator.pipeline import process_message
from app.orchestrator.pipeline_types import Deps
from app.pricing.quote_number import fiscal_year
from app.repositories.catalog import CatalogRepository
from app.repositories.chat import ChatRepository
from app.repositories.leads import LeadRepository
from app.repositories.pricing_rules import PricingRuleRepository, RequirementSchemaRepository
from app.repositories.quotes import QuoteRepository
from app.services.quotes import LineEdit, ProposedLine, QuoteService
from seeds.data import PHOTOGRAPHER, PRINTING, DemoBusiness
from seeds.load import load_business
from tests.conftest import PASSWORD, make_tenant, unique_email
from tests.helpers import quote_router, router

EMBEDDER = FakeEmbedder()


async def make_shop(
    sessionmaker: SessionMaker, settings: Settings, business: DemoBusiness
) -> TenantContext:
    ctx = await load_business(
        sessionmaker, replace(business, owner_email=unique_email()), PASSWORD, settings
    )
    assert ctx is not None
    await build_handlers(EMBEDDER, settings, FakeLLM([]))["embed_catalog_items"](
        sessionmaker, ctx, {}
    )
    return ctx


class Talk:
    def __init__(self, sm: SessionMaker, settings: Settings, ctx: TenantContext) -> None:
        self.sm, self.settings, self.ctx = sm, settings, ctx
        self.conversation_id: uuid.UUID | None = None

    async def say(self, text: str, replies: list[str]) -> tuple[FakeLLM, list[Message]]:
        async with self.sm() as session:
            chat = ChatRepository(session, self.ctx)
            conversation = (
                await chat.get_conversation(self.conversation_id)
                if self.conversation_id
                else await chat.start_conversation(Channel.PLAYGROUND, "Asha Traders")
            )
            assert conversation is not None
            self.conversation_id = conversation.id
            await chat.add_message(
                conversation, direction=Direction.IN, sender_type=SenderType.CUSTOMER, content=text
            )
            await session.commit()
        llm = FakeLLM(replies)
        await process_message(
            Deps(llm, EMBEDDER, self.settings, self.sm),
            self.ctx,
            {"conversation_id": str(self.conversation_id)},
        )
        return llm, await self.messages()

    async def messages(self) -> list[Message]:
        async with self.sm() as session:
            assert self.conversation_id
            return await ChatRepository(session, self.ctx).messages(self.conversation_id)

    async def quotes(self) -> list[Quote]:
        async with self.sm() as session:
            return await QuoteRepository(session, self.ctx).browse()

    @property
    def cid(self) -> uuid.UUID:
        assert self.conversation_id
        return self.conversation_id

    def service(self, session: AsyncSession) -> QuoteService:
        return QuoteService(session, self.ctx, self.settings)


def collect(
    category: str | None,
    filled: dict[str, object],
    questions: list[str] | None = None,
    unknown: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "category": category,
            "filled": filled,
            "questions": questions or [],
            "unknown_slots": unknown or [],
        }
    )


def mapping(*lines: dict[str, object], unmapped: list[str] | None = None) -> str:
    return json.dumps({"lines": list(lines), "unmapped": unmapped or []})


def pdf_text(data: bytes) -> str:
    return "".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


@pytest.fixture
async def printing(sessionmaker: SessionMaker, settings: Settings) -> Talk:
    return Talk(sessionmaker, settings, await make_shop(sessionmaker, settings, PRINTING))


# --- acceptance: a printing quote ------------------------------------------------------------


async def test_printing_conversation_ends_in_the_hand_calculated_quote(printing: Talk) -> None:
    # Turn 1: we do not know enough yet, so the assistant asks. (A question never carries money.)
    llm, messages = await printing.say(
        "I need some printing done",
        [
            quote_router(),
            collect("printing", {}, ["What would you like to print, and how many?"]),
            json.dumps({"reply": "Happy to help! What would you like to print, and how many?"}),
        ],
    )
    assert "What would you like to print" in messages[-1].content
    assert await printing.quotes() == []

    # Turn 2: a short answer. The router is unsure, but a quote is in progress, so it stays in.
    llm, messages = await printing.say(
        "500 visiting cards, matt lamination please",
        [
            router("general_faq", confidence=0.3),
            collect(
                "printing",
                {"item_type": "visiting card", "quantity": "500", "finishing": "matt lamination"},
            ),
            mapping(
                {
                    "sku": "VC-STD",
                    "description": "Visiting card",
                    "quantity": 500,
                    "addon_codes": ["LAM-MATT"],
                }
            ),
        ],
    )
    # The customer is told a quote is coming, and NOT what it costs: the owner approves first.
    assert messages[-1].content == canned("quote_pending", "en")
    assert all("₹" not in m.content and "1,652" not in m.content for m in messages)
    # The model was never shown a price when matching items, and the SKU list came from the shop.
    mapping_prompt = " ".join(m.content for m in llm.calls[-1][1])
    assert "sku=VC-STD" in mapping_prompt and "LAM-MATT" in mapping_prompt
    assert "₹" not in mapping_prompt and "25000" not in mapping_prompt

    (quote,) = await printing.quotes()
    assert quote.quote_number == f"Q/{fiscal_year(date.today())}/0001"
    assert quote.status == QuoteStatus.PENDING_APPROVAL
    async with printing.sm() as session:
        view = await printing.service(session).view(quote.id)
    # 500 cards = 5 x "per 100". Tier price Rs 235; matt lamination Rs 45 per 100.
    # 5 x 235 = 1,175 + 5 x 45 = 225 -> taxable 1,400; GST 18% = 252 (CGST 126 + SGST 126).
    assert [(i.description, i.qty, i.unit_price_paise, i.line_total_paise) for i in view.items] == [
        ("Visiting card (100 pcs)", D("5.000"), 23500, 117500),
        ("Matt lamination", D("5.000"), 4500, 22500),
    ]
    assert (view.totals.taxable_paise, view.totals.cgst_paise, view.totals.sgst_paise) == (
        140000,
        12600,
        12600,
    )
    assert (quote.total_paise, quote.round_off_paise, quote.igst_paise) == (165200, 0, 0)

    # The lead exists, is qualified, scored, and knows what it is worth.
    async with printing.sm() as session:
        lead = await LeadRepository(session, printing.ctx).for_conversation(printing.cid)
        assert lead is not None
        events = [e.event_type for e in await LeadRepository(session, printing.ctx).events(lead.id)]
    assert lead.stage == LeadStage.QUALIFIED and lead.estimated_value_paise == 165200
    assert lead.category == "printing" and lead.requirements["quantity"] == 500
    assert lead.score > 0 and events[0] == "created" and "quote_created" in events

    # The PDF carries the same numbers.
    async with printing.sm() as session:
        preview = pdf_text(await printing.service(session).pdf(quote.id))
    for expected in (
        quote.quote_number,
        "Rs. 1,652.00",
        "24ABCDE1234F1Z5",
        "Asha Traders",
        "Rupees One Thousand Six Hundred Fifty-Two Only",
        "50 percent advance",
    ):
        assert expected in preview, expected

    # The owner approves: the customer now gets the total, the PDF is frozen, the lead moves on.
    async with printing.sm() as session:
        await printing.service(session).approve(quote.id)
        await session.commit()
    sent = (await printing.messages())[-1]
    assert sent.quote_id == quote.id and sent.sender_type == SenderType.STAFF
    assert "₹1,652.00" in sent.content and quote.quote_number in sent.content
    async with printing.sm() as session:
        approved = await QuoteRepository(session, printing.ctx).get(quote.id)
        assert approved is not None
        assert approved.status == QuoteStatus.SENT and approved.pdf_path and approved.approved_by
        assert pdf_text(await printing.service(session).pdf(quote.id)) == preview
        lead = await LeadRepository(session, printing.ctx).for_conversation(printing.cid)
        assert lead is not None and lead.stage == LeadStage.QUOTED
        with pytest.raises(ConflictError):
            await printing.service(session).approve(quote.id)  # cannot send it twice

        await printing.service(session).mark_accepted(quote.id)
        await session.commit()
    async with printing.sm() as session:
        lead = await LeadRepository(session, printing.ctx).for_conversation(printing.cid)
    assert lead is not None and lead.stage == LeadStage.WON


# --- acceptance: a photography quote ---------------------------------------------------------


async def test_photography_conversation_ends_in_the_hand_calculated_quote(
    sessionmaker: SessionMaker, settings: Settings
) -> None:
    talk = Talk(sessionmaker, settings, await make_shop(sessionmaker, settings, PHOTOGRAPHER))
    _, messages = await talk.say(
        "Wedding on 12 Dec in Surat, 2 days, we need photos and video",
        [
            quote_router(),
            collect(
                "photography",
                {
                    "event_type": "wedding",
                    "event_date": "12 Dec",
                    "city": "Surat",
                    "days": 2,
                    "deliverables": ["Photos", "video", "hologram"],
                },
            ),
            mapping(
                {"sku": "WED-2D", "description": "2 day wedding", "quantity": 1},
                {"sku": "WED-VID", "description": "Wedding video", "quantity": 1},
            ),
        ],
    )
    assert messages[-1].content == canned("quote_pending", "en")
    (quote,) = await talk.quotes()
    # 80,000 + 30,000 = 1,10,000 ; GST 18% = 19,800 (9,900 + 9,900) ; total 1,29,800
    assert (quote.subtotal_paise, quote.cgst_paise, quote.sgst_paise) == (
        11_000_000,
        990_000,
        990_000,
    )
    assert quote.total_paise == 12_980_000
    async with sessionmaker() as session:
        lead = await LeadRepository(session, talk.ctx).for_conversation(talk.cid)
        text = pdf_text(await talk.service(session).pdf(quote.id))
    assert lead is not None and lead.requirements["deliverables"] == ["photos", "video"]
    assert "Rs. 1,29,800.00" in text and "One Lakh Twenty-Nine Thousand Eight Hundred" in text


# --- the model proposes, the code decides ----------------------------------------------------


async def test_made_up_items_bad_addons_and_prices_from_the_model_are_ignored(
    printing: Talk,
) -> None:
    await printing.say(
        "100 visiting cards and a unicorn statue",
        [
            quote_router(),
            collect("printing", {"item_type": "visiting card", "quantity": 100}),
            mapping(
                {"sku": "MADE-UP-1", "description": "Unicorn statue", "quantity": 1, "price": 1},
                {
                    "sku": "VC-STD",
                    "quantity": 100,
                    "price_paise": 1,
                    "addon_codes": ["FREE-EVERYTHING", "LAM-MATT"],
                },
                {"sku": "FLEX-STD", "description": "Banner", "quantity": "lots"},
                unmapped=["Gold plating"],
            ),
        ],
    )
    (quote,) = await printing.quotes()
    async with printing.sm() as session:
        view = await printing.service(session).view(quote.id)
    by_desc = {i.description: i for i in view.items}
    # the invented SKU, the unreadable quantity and the unmapped need all wait for the owner
    unpriced = [i for i in view.items if i.needs_owner_pricing]
    assert {i.description for i in unpriced} == {
        "Unicorn statue (price to be confirmed)",
        "Banner (price to be confirmed)",
        "Gold plating (price to be confirmed)",
    }
    assert all(i.unit_price_paise == 0 and i.line_total_paise == 0 for i in unpriced)
    # the real item is priced from the catalogue; the model's "price" fields changed nothing,
    # and the add-on that does not exist was dropped while the real one stayed
    assert by_desc["Visiting card (100 pcs)"].unit_price_paise == 25000
    assert by_desc["Visiting card (100 pcs)"].qty == D("1.000")
    assert by_desc["Matt lamination"].line_total_paise == 4500
    assert view.totals.taxable_paise == 29500

    async with printing.sm() as session:  # cannot send a quote with lines nobody has priced
        with pytest.raises(ConflictError, match="Price every line"):
            await printing.service(session).approve(quote.id)
        service = printing.service(session)
        edits = [LineEdit(i.id, unit_price_paise=5000) for i in unpriced]
        fixed = await service.update(quote.id, edits, None, set_buyer_state=False)
        assert not any(i.needs_owner_pricing for i in fixed.items)
        assert fixed.totals.taxable_paise == 29500 + 3 * 5000
        await service.approve(quote.id)


async def test_an_area_priced_item_is_sized_by_code_with_tiers_addons_and_round_off(
    printing: Talk,
) -> None:
    async with printing.sm() as session:
        flex = await CatalogRepository(session, printing.ctx).by_sku("FLEX-STD")
        assert flex is not None
        lead_conv = await ChatRepository(session, printing.ctx).start_conversation(
            Channel.PLAYGROUND
        )
        lead = await sync_lead(session, printing.ctx, lead_conv)
        quote, notes = await printing.service(session).create(
            lead.id,
            [ProposedLine("Flex", flex.id, D(1), D(12), D(10), ("EYELETS",))],
        )
        await session.commit()
        view = await printing.service(session).view(quote.id)
    # 12 ft x 10 ft = 120 sq ft: the 100+ tier is Rs 16 -> 1,920 ; eyelets 100 once ; taxable 2,020
    # GST 18% = 363.60 (181.80 + 181.80) ; total before round-off 2,383.60 -> 2,384 (+0.40)
    assert notes == []
    assert [(i.qty, i.unit_price_paise, i.line_total_paise) for i in view.items] == [
        (D("120.000"), 1600, 192000),
        (D("1.000"), 10000, 10000),
    ]
    assert (quote.cgst_paise, quote.sgst_paise) == (18180, 18180)
    assert (quote.round_off_paise, quote.total_paise) == (40, 238400)


async def test_rule_violations_are_reported_to_the_owner_not_hidden(printing: Talk) -> None:
    async with printing.sm() as session:
        card = await CatalogRepository(session, printing.ctx).by_sku("VC-STD")
        assert card is not None
        conv = await ChatRepository(session, printing.ctx).start_conversation(Channel.PLAYGROUND)
        lead = await sync_lead(session, printing.ctx, conv)
        # 50 cards is half a unit, below the minimum of 1 unit
        _, notes = await printing.service(session).create(
            lead.id, [ProposedLine("cards", card.id, D(50))]
        )
    assert any("minimum order" in n for n in notes)


# --- editing and the quote life cycle ---------------------------------------------------------


async def _quote(printing: Talk) -> uuid.UUID:
    async with printing.sm() as session:
        card = await CatalogRepository(session, printing.ctx).by_sku("VC-STD")
        assert card is not None
        conv = await ChatRepository(session, printing.ctx).start_conversation(Channel.PLAYGROUND)
        lead = await sync_lead(session, printing.ctx, conv)
        quote, _ = await printing.service(session).create(
            lead.id, [ProposedLine("cards", card.id, D(500))]
        )
        await session.commit()
        return quote.id


async def test_owner_edits_are_recomputed_by_the_engine(printing: Talk) -> None:
    quote_id = await _quote(printing)
    async with printing.sm() as session:
        service = printing.service(session)
        view = await service.view(quote_id)
        line = view.items[0]
        assert line.line_total_paise == 117500  # 5 x 235
        edited = await service.update(
            quote_id,
            [LineEdit(line.id, qty=D(10), discount_paise=10000)],
            None,
            set_buyer_state=False,
        )
        # 10 x 235 = 2,350 less 100 discount = 2,250 ; GST 18% = 405 ; total 2,655
        assert edited.items[0].line_total_paise == 225000
        assert (edited.quote.discount_paise, edited.quote.total_paise) == (10000, 265500)
        # a different state turns CGST+SGST into IGST
        inter = await service.update(quote_id, [], "27", set_buyer_state=True)
        assert (inter.quote.cgst_paise, inter.quote.igst_paise) == (0, 40500)
        cleared = await service.update(quote_id, [], None, set_buyer_state=True)
        assert cleared.quote.buyer_state_code is None and cleared.quote.igst_paise == 0
        with pytest.raises(FileRejectedError):  # a discount larger than the line
            await service.update(
                quote_id, [LineEdit(line.id, discount_paise=10**9)], None, set_buyer_state=False
            )
        with pytest.raises(NotFoundError):
            await service.update(
                quote_id, [LineEdit(uuid.uuid4(), qty=D(1))], None, set_buyer_state=False
            )
        await service.approve(quote_id)
        with pytest.raises(ConflictError):  # a sent quote is frozen
            await service.update(quote_id, [], None, set_buyer_state=False)


async def test_reject_accept_and_expiry_rules(printing: Talk) -> None:
    first, second, third = await _quote(printing), await _quote(printing), await _quote(printing)
    async with printing.sm() as session:
        service = printing.service(session)
        await service.reject(first)
        with pytest.raises(ConflictError):
            await service.approve(first)
        with pytest.raises(ConflictError):
            await service.reject(first)
        with pytest.raises(ConflictError):
            await service.mark_accepted(second)  # not sent yet
        expired = await QuoteRepository(session, printing.ctx).get(third)
        assert expired is not None
        expired.valid_until = date.today() - timedelta(days=3)
        with pytest.raises(ConflictError, match="expired"):
            await service.approve(third)
        await session.commit()


async def test_quote_numbers_are_unique_and_restart_each_financial_year(
    sessionmaker: SessionMaker,
) -> None:
    ctx = await make_tenant(sessionmaker)

    async def take(day: date) -> str:
        async with sessionmaker() as session:
            number = await QuoteRepository(session, ctx).next_number(day)
            await session.commit()
            return number

    numbers = await asyncio.gather(*[take(date(2026, 11, 15)) for _ in range(8)])
    assert sorted(numbers) == [f"Q/2026-27/{n:04d}" for n in range(1, 9)]  # no duplicates, no gaps
    assert await take(date(2027, 3, 31)) == "Q/2026-27/0009"  # still the same financial year
    assert await take(date(2027, 4, 1)) == "Q/2027-28/0001"  # April starts a new sequence
    other = await make_tenant(sessionmaker)
    async with sessionmaker() as session:  # another business has its own counter
        assert (
            await QuoteRepository(session, other).next_number(date(2026, 11, 15))
            == "Q/2026-27/0001"
        )


# --- the guardrail still guards questions ----------------------------------------------------


async def test_a_question_that_mentions_money_is_blocked(printing: Talk) -> None:
    _, messages = await printing.say(
        "I need a quote",
        [
            quote_router(),
            collect("printing", {}, ["What do you need? Cards start at just ₹5!"]),
            json.dumps({"reply": "Cards start at just ₹5! What do you need?"}),
            json.dumps({"reply": "Special offer: only ₹99!"}),
        ],
    )
    assert all("₹5" not in m.content and "₹99" not in m.content for m in messages)
    assert "connecting you with our team" in messages[-1].content  # a person takes over
    async with printing.sm() as session:
        conversation = await ChatRepository(session, printing.ctx).get_conversation(printing.cid)
    assert conversation is not None and conversation.mode == ConversationMode.HUMAN


async def test_without_requirement_schemas_the_team_follows_up_by_hand(
    sessionmaker: SessionMaker, settings: Settings
) -> None:
    talk = Talk(sessionmaker, settings, await make_tenant(sessionmaker))
    _, messages = await talk.say("quote please", [quote_router()])
    assert messages[-1].content == canned("quote_pending", "en")


async def test_dont_know_answers_use_defaults_and_do_not_block_the_quote(printing: Talk) -> None:
    await printing.say(
        "500 visiting cards, no idea about size or finish",
        [
            quote_router(),
            collect(
                "printing",
                {"item_type": "visiting card", "quantity": 500},
                unknown=["size", "finishing", "bogus"],
            ),
            mapping({"sku": "VC-STD", "quantity": 500}),
        ],
    )
    (quote,) = await printing.quotes()
    async with printing.sm() as session:
        lead = await LeadRepository(session, printing.ctx).for_conversation(printing.cid)
    assert lead is not None
    assert lead.requirements["size"] == "standard" and lead.requirements["finishing"] == "none"
    assert "bogus" not in lead.requirements and quote.total_paise > 0


# --- tenant isolation ------------------------------------------------------------------------


async def test_quotes_rules_schemas_and_leads_are_tenant_isolated(
    printing: Talk, sessionmaker: SessionMaker, settings: Settings
) -> None:
    quote_id = await _quote(printing)
    other = await make_shop(sessionmaker, settings, PHOTOGRAPHER)
    async with sessionmaker() as session:
        theirs = QuoteService(session, other, settings)
        with pytest.raises(NotFoundError):
            await theirs.view(quote_id)
        for action in (theirs.approve, theirs.reject, theirs.mark_accepted, theirs.pdf):
            with pytest.raises(NotFoundError):
                await action(quote_id)
        assert await QuoteRepository(session, other).summaries() == []
        mine = await CatalogRepository(session, printing.ctx).by_sku("VC-STD")
        assert mine is not None
        assert await PricingRuleRepository(session, other).applying_to(mine) == []
        assert {s.category for s in await RequirementSchemaRepository(session, other).browse()} == {
            "photography"
        }
        assert await LeadRepository(session, other).browse() == []
        with pytest.raises(NotFoundError):
            await theirs.update(quote_id, [], None, set_buyer_state=False)
    # and the owner's own quote is untouched
    async with sessionmaker() as session:
        again = await QuoteRepository(session, printing.ctx).get(quote_id)
        assert again is not None and again.status == QuoteStatus.PENDING_APPROVAL
        rows = (
            await session.scalars(select(Quote).where(Quote.tenant_id == other.tenant_id))
        ).all()
        assert list(rows) == []
