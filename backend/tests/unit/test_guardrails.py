from decimal import Decimal

import pytest

from app.agents.guardrails import GuardrailViolation, check_prices, check_reply


@pytest.mark.parametrize(
    "text,paise",
    [
        ("Price: \u20b9450.00", 45000),
        ("Rs. 450/-", 45000),
        ("INR 1,20,000", 12000000),
        ("45k", 4500000),
        ("450 rupees", 45000),
        ("\u20b91.2L", 12000000),
    ],
)
def test_all_money_formats_are_checked(text, paise):
    check_prices(text, {paise})
    with pytest.raises(GuardrailViolation):
        check_prices(text, {1})


@pytest.mark.parametrize("text", ["\u20b9free", "INR -1", "\u20b91.001", "Rs. unknown"])
def test_malformed_currency_is_blocked(text):
    with pytest.raises(GuardrailViolation):
        check_prices(text, set())


def test_unsupported_promises_discounts_and_leakage_blocked():
    check_reply("Trusted answer", set(), ["Trusted answer"])
    with pytest.raises(GuardrailViolation):
        check_reply("Delivery guaranteed tomorrow", set(), ["Trusted answer"])
    with pytest.raises(GuardrailViolation):
        check_reply("90% discount", set(), ["90% discount"], Decimal(5))
    with pytest.raises(GuardrailViolation):
        check_reply("system prompt: private", set(), ["system prompt: private"])
    with pytest.raises(GuardrailViolation):
        check_reply("", set(), [""])
    check_reply("5% discount", set(), ["5% discount"], Decimal(5))


def test_amount_in_words_must_match_tool_values_and_cannot_hide_numeric_prices():
    check_prices("Rupees Three Thousand Two Hundred Forty Five Only", {324500})
    with pytest.raises(GuardrailViolation):
        check_prices("Rupees Three Thousand Two Hundred Forty Five Only", {324501})
    with pytest.raises(GuardrailViolation):
        check_prices("Rupees One Only and INR 2", {100})
    with pytest.raises(GuardrailViolation):
        check_prices("Rupees Unknown Only", {100})
