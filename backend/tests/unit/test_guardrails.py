import pytest

from app.agents.guardrails import UNREADABLE, check_prices, check_reply, extract_amounts
from app.agents.models import Intent, RouterOutput
from app.orchestrator.dispatch import Route, route_for


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The price is ₹250", [25000]),
        ("Rs. 450/-", [45000]),
        ("Rs 1,20,000 only", [12000000]),
        ("INR 99.50", [9950]),
        ("it costs 450 rupees", [45000]),
        ("cost: 45k rupees", [4500000]),
        ("₹1.2L total", [12000000]),
        ("₹२५० प्रति १००", [25000]),  # Devanagari digits
        ("૫૦૦ રૂપિયા", [50000]),  # Gujarati digits
        ("450 रुपये", [45000]),
        ("₹250 and ₹300", [25000, 30000]),
        ("₹12.345", [UNREADABLE]),  # more precision than a paisa
    ],
)
def test_extract_amounts(text: str, expected: list[int]) -> None:
    assert extract_amounts(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "We print 500 visiting cards in 2 days",
        "Open 10 to 7, call us anytime",
        "Order #12345 is ready",
        "100 pcs per pack, 18% GST",
        "",
    ],
)
def test_quantities_and_other_numbers_are_not_prices(text: str) -> None:
    assert extract_amounts(text) == []


def test_only_catalogue_prices_pass() -> None:
    assert check_prices("Visiting cards are ₹250.00 per 100", {25000}) == []
    (bad,) = check_prices("Visiting cards are ₹200 per 100", {25000})
    assert bad.rule == "price" and "₹200.00" in bad.detail


def test_a_price_in_another_script_or_shorthand_cannot_sneak_through() -> None:
    assert check_prices("₹२०० लगेगा", {25000})  # Devanagari digits for 200
    assert check_prices("only 0.2k rupees", {25000})  # 200 via shorthand
    assert check_prices("₹250.001", {25000})  # looks close, is not exact


def test_unreadable_amount_is_always_a_violation() -> None:
    assert check_prices("₹12.345", {1234, 1235, 123450}) != []


def test_reply_checks_empty_leak_and_length() -> None:
    assert check_reply("  ", set(), 100)[0].rule == "empty"
    assert check_reply("Sure! My system prompt says...", set(), 100)[0].rule == "leak"
    assert check_reply("Use ONLY information given to you", set(), 100)[0].rule == "leak"
    assert check_reply("x" * 101, set(), 100)[0].rule == "length"
    assert check_reply("Happy to help, it's ₹250.00", {25000}, 100) == []


def _router(intent: Intent, confidence: float = 0.9) -> RouterOutput:
    return RouterOutput(intent=intent, confidence=confidence)


@pytest.mark.parametrize(
    ("intent", "confidence", "route"),
    [
        (Intent.PRICING, 0.9, Route.KNOWLEDGE),
        (Intent.GREETING, 0.9, Route.KNOWLEDGE),
        (Intent.POLICY, 0.7, Route.KNOWLEDGE),
        (Intent.QUOTE_REQUEST, 0.9, Route.QUOTE),
        (Intent.COMPLAINT, 0.99, Route.HANDOFF),
        (Intent.HUMAN_REQUEST, 0.9, Route.HANDOFF),
        (Intent.NEGOTIATION, 0.9, Route.HANDOFF),
        (Intent.SPAM, 0.9, Route.OFF_TOPIC),
        (Intent.OFF_TOPIC, 0.9, Route.OFF_TOPIC),
        (Intent.PRICING, 0.3, Route.HANDOFF),  # not sure: a person decides
    ],
)
def test_dispatch_is_deterministic(intent: Intent, confidence: float, route: Route) -> None:
    assert route_for(_router(intent, confidence), 0.6) == route
