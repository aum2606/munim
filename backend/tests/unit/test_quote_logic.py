"""Pure logic around quoting: requirement slots, lead scoring, routing, units, the PDF."""

import io
from datetime import date
from decimal import Decimal as D

import pytest
from pypdf import PdfReader

from app.agents.models import Intent, RouterOutput
from app.db.models import LeadStage, QuoteStatus
from app.orchestrator.dispatch import Route, route_for
from app.orchestrator.leads import LeadSignals, auto_stage, lead_score
from app.orchestrator.requirements import (
    apply_unknowns,
    missing_slots,
    next_questions,
    required_slots,
    validate_slots,
)
from app.pricing.engine import PricedLine, quote_totals
from app.quotes.pdf import PdfLine, QuotePdf, render_quote_pdf
from app.services.quotes import billable_qty, pack_size

SCHEMA = {
    "properties": {
        "item_type": {"type": "string"},
        "quantity": {"type": "integer"},
        "area": {"type": "number"},
        "sides": {"type": "string", "enum": ["single", "double"]},
        "extras": {"type": "array", "items": {"enum": ["photos", "video"]}},
    },
    "required": ["item_type", "quantity", "ghost"],
}


def test_required_slots_ignore_names_the_schema_does_not_define() -> None:
    assert required_slots(SCHEMA) == ["item_type", "quantity"]
    assert required_slots({}) == []
    assert required_slots({"properties": "nonsense"}) == []


def test_slot_values_are_kept_only_when_valid_for_their_type() -> None:
    clean = validate_slots(
        SCHEMA,
        {
            "item_type": "  visiting card ",
            "quantity": "1,500",
            "area": "2.50",
            "sides": "DOUBLE",
            "extras": ["Photos", "drone", "video"],
            "invented": "x",  # not in the schema
        },
    )
    assert clean == {
        "item_type": "visiting card",
        "quantity": 1500,
        "area": "2.5",
        "sides": "double",
        "extras": ["photos", "video"],
    }


@pytest.mark.parametrize(
    ("slot", "value"),
    [
        ("quantity", "5.5"),  # an integer slot refuses fractions
        ("quantity", 0),
        ("quantity", -3),
        ("quantity", True),  # a boolean is not a number
        ("quantity", "lots"),
        ("quantity", 10**9),
        ("area", None),
        ("item_type", "   "),
        ("item_type", None),
        ("sides", "both"),  # not an allowed option
        ("extras", ["drone"]),
        ("extras", []),
    ],
)
def test_invalid_slot_values_are_dropped_not_repaired(slot: str, value: object) -> None:
    assert slot not in validate_slots(SCHEMA, {slot: value})


def test_long_text_is_cut_to_a_sane_length() -> None:
    assert len(validate_slots(SCHEMA, {"item_type": "x" * 1000})["item_type"]) == 200


def test_dont_know_uses_the_default_or_marks_not_specified() -> None:
    schema = {"properties": {"sides": {"type": "string"}, "size": {"type": "string"}}}
    got = apply_unknowns(schema, {"sides": "double"}, {}, ["sides", "size", "nope"])
    assert got == {"sides": "double", "size": "not specified"}  # unknown slot names are ignored
    keep = apply_unknowns(schema, {"sides": "double"}, {"sides": "single"}, ["sides"])
    assert keep == {"sides": "single"}  # something already said is never overwritten


def test_missing_slots_and_the_two_question_limit() -> None:
    assert missing_slots(SCHEMA, {"item_type": "card"}) == ["quantity"]
    assert missing_slots(SCHEMA, {"item_type": "card", "quantity": 5}) == []
    asked = next_questions(["How many?", "What size?", "By when?"], ["quantity"], {})
    assert asked == ["How many?", "What size?"]
    assert next_questions([" ", ""], ["quantity", "item_type", "x"], {"quantity": "How many?"}) == [
        "How many?",
        "Could you tell us the item type?",
    ]


def _signals(**kw: object) -> LeadSignals:
    base: dict[str, object] = {
        "has_phone": False,
        "requirements_filled": 0,
        "requirements_total": 0,
        "quote_status": None,
        "customer_messages": 0,
        "hours_since_last_message": None,
        "sentiment": None,
    }
    return LeadSignals(**{**base, **kw})  # type: ignore[arg-type]


def test_lead_score_components_are_explainable() -> None:
    assert lead_score(_signals()) == 0
    assert lead_score(_signals(has_phone=True)) == 15
    assert lead_score(_signals(requirements_filled=1, requirements_total=2)) == 12
    assert lead_score(_signals(requirements_filled=5, requirements_total=2)) == 25  # capped
    assert lead_score(_signals(quote_status=QuoteStatus.PENDING_APPROVAL)) == 10
    assert lead_score(_signals(quote_status=QuoteStatus.SENT)) == 25
    assert lead_score(_signals(quote_status=QuoteStatus.REJECTED)) == 0
    assert lead_score(_signals(customer_messages=3)) == 12
    assert lead_score(_signals(customer_messages=50)) == 20  # capped at 5 messages
    for hours, points in ((1, 15), (30, 8), (100, 3), (500, 0)):
        assert lead_score(_signals(hours_since_last_message=hours)) == points
    assert lead_score(_signals(has_phone=True, sentiment="positive")) == 20
    assert lead_score(_signals(sentiment="negative")) == 0  # never below zero
    full = _signals(
        has_phone=True,
        requirements_filled=2,
        requirements_total=2,
        customer_messages=9,
        quote_status=QuoteStatus.ACCEPTED,
        hours_since_last_message=1,
        sentiment="positive",
    )
    assert lead_score(full) == 100  # 15+25+25+20+15+5 = 105, capped


@pytest.mark.parametrize(
    ("current", "kw", "expected"),
    [
        (LeadStage.NEW, {}, LeadStage.NEW),
        (LeadStage.NEW, {"customer_messages": 2}, LeadStage.ENGAGED),
        (LeadStage.ENGAGED, {"requirements_complete": True}, LeadStage.QUALIFIED),
        (LeadStage.NEW, {"quote_status": QuoteStatus.PENDING_APPROVAL}, LeadStage.QUALIFIED),
        (LeadStage.QUALIFIED, {"quote_status": QuoteStatus.SENT}, LeadStage.QUOTED),
        (LeadStage.QUOTED, {"negotiating": True}, LeadStage.NEGOTIATING),
        (LeadStage.NEGOTIATING, {"quote_status": QuoteStatus.SENT}, LeadStage.NEGOTIATING),
        (LeadStage.QUOTED, {"customer_messages": 5}, LeadStage.QUOTED),  # never backwards
        (LeadStage.QUOTED, {"quote_status": QuoteStatus.ACCEPTED}, LeadStage.WON),
        (LeadStage.WON, {"negotiating": True}, LeadStage.WON),  # final stages are left alone
        (LeadStage.LOST, {"quote_status": QuoteStatus.SENT}, LeadStage.LOST),
        (LeadStage.DORMANT, {"customer_messages": 9}, LeadStage.DORMANT),
    ],
)
def test_stage_only_moves_forward(
    current: LeadStage, kw: dict[str, object], expected: LeadStage
) -> None:
    args: dict[str, object] = {
        "customer_messages": 0,
        "requirements_complete": False,
        "quote_status": None,
        "negotiating": False,
    }
    assert auto_stage(current, **{**args, **kw}) == expected  # type: ignore[arg-type]


def _router(intent: Intent, confidence: float = 0.9) -> RouterOutput:
    return RouterOutput(intent=intent, confidence=confidence)


def test_an_active_quote_flow_keeps_short_answers_in_the_flow() -> None:
    assert route_for(_router(Intent.GENERAL_FAQ, 0.2), 0.6, True) == Route.QUOTE  # "500"
    assert route_for(_router(Intent.OFF_TOPIC), 0.6, True) == Route.QUOTE
    assert route_for(_router(Intent.GENERAL_FAQ, 0.2), 0.6, False) == Route.HANDOFF
    # a complaint mid-quote still goes to a person
    assert route_for(_router(Intent.COMPLAINT), 0.6, True) == Route.HANDOFF
    assert route_for(_router(Intent.NEGOTIATION), 0.6, True) == Route.HANDOFF


def test_pack_sizes_are_piece_counts_only() -> None:
    assert pack_size("per 100") == 100 and pack_size("per 100 pcs") == 100
    assert pack_size("Per 1000 Pieces") == 1000 and pack_size("per 50") == 50
    for unit in ("per 2 days", "per sq ft", "per book", "each", "per event", "per 100 sq ft"):
        assert pack_size(unit) == 1, unit


def test_billable_quantity_is_computed_in_decimal_by_code() -> None:
    assert billable_qty("per 100", D(500), None, None) == D("5.000")
    assert billable_qty("per 100", D(550), None, None) == D("5.500")  # pro rata
    assert billable_qty("per piece", D(3), None, None) == D("3.000")
    assert billable_qty("per sq ft", D(2), D(10), D(4)) == D("80.000")
    assert billable_qty("per sq ft", D(1), None, D(4)) is None  # size needed but missing
    assert billable_qty("per sq ft", D(1), D(0), D(4)) is None
    assert billable_qty("per 100", D(0), None, None) is None
    assert billable_qty("per 100", D(10**9), None, None) is None  # absurd quantity
    assert billable_qty("per 100", D(1), None, None) == D("0.010")


def _pdf() -> bytes:
    lines = [
        PdfLine("Visiting card (100 pcs)", "4911", D(5), "per 100", 23500, 0, 18, 117500),
        PdfLine("Matt lamination <b>bold</b>", "4911", D(5), "per 100", 4500, 0, 18, 22500),
    ]
    priced = [
        PricedLine(
            x.description, x.unit, x.qty, x.unit_price_paise, 0, 18, None, None, x.line_total_paise
        )
        for x in lines
    ]
    return render_quote_pdf(
        QuotePdf(
            seller_name="Shree Ganesh Printing Press",
            seller_gstin="24ABCDE1234F1Z5",
            seller_address="Shop 12, Ring Road, Surat",
            seller_phone="+91 90000 00001",
            seller_state="24",
            buyer_name="Asha & Sons <script>",
            buyer_phone=None,
            buyer_state=None,
            quote_number="Q/2026-27/0001",
            issued_on=date(2026, 11, 15),
            valid_until=date(2026, 11, 22),
            lines=lines,
            totals=quote_totals(priced, "24", None),
            terms="50 percent advance.",
        )
    )


def test_the_pdf_prints_the_numbers_it_is_given() -> None:
    data = _pdf()
    assert data.startswith(b"%PDF")
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
    for expected in (
        "Q/2026-27/0001",
        "24ABCDE1234F1Z5",
        "Rs. 1,652.00",
        "Rs. 126.00",
        "Rupees One Thousand Six Hundred Fifty-Two Only",
        "50 percent advance.",
        "HSN/SAC",
    ):
        assert expected in text, expected
    assert "<b>bold</b>" in text  # owner and customer text is printed, never interpreted as markup
    assert "Asha & Sons" in text
