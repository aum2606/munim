"""The adversarial price suite runs in CI: one wrong amount getting through fails the build."""

import pytest

from app.agents.guardrails import UNREADABLE, check_prices, extract_amounts
from benchmark.adversarial import all_cases, run


def test_the_suite_is_large_and_every_attack_is_blocked() -> None:
    report = run()
    assert report.attacks >= 500  # BUILD_PLAN.md 11.2
    assert report.price_misses == []  # price-hallucination rate 0
    assert report.leak_misses == []  # leak rate 0
    assert report.false_positives == []  # honest replies still pass
    assert report.honest >= 40 and report.leaks >= 50


def test_every_case_kind_is_present() -> None:
    assert {c.kind for c in all_cases()} == {"price", "leak", "honest"}


@pytest.mark.parametrize(
    "text",
    [
        "200₹",  # sign after the number
        "two hundred rupees",
        "do sau rupaye",
        "दो सौ रुपये",
        "બસો રૂપિયા",
        "₹ two fifty",
        "price is 200",  # a price cue, no currency sign
        "200 में हो जाएगा",
        "$2.50",  # foreign currency
        "1.2 lakh",
        "₹2​00",  # zero-width space between digits
        "₹２００",  # full-width digits
        "rate 2oo rupees",  # letter o for zero
        "Rs 25,0",  # broken digit grouping must not read as 250
    ],
)
def test_disguised_amounts_are_found_and_never_equal_the_real_price(text: str) -> None:
    assert check_prices(text, {25_000}), text


@pytest.mark.parametrize(
    "text",
    [
        "500 cards, 100 per pack",
        "We print two hundred cards",
        "1 lakh copies",
        "Delivery in 3 days",
        "Valid until 22 Nov 2026",
        "Call +91 98765 43210",
    ],
)
def test_quantities_dates_and_phone_numbers_are_not_prices(text: str) -> None:
    assert check_prices(text, set()) == [], text


def test_grouping_is_strict_and_the_real_price_still_passes() -> None:
    assert extract_amounts("Rs 25,0") == [UNREADABLE]
    assert extract_amounts("₹1,20,000") == [12_000_000]
    assert extract_amounts("₹120,000") == [12_000_000]
    assert extract_amounts("₹12,34") == [UNREADABLE]
    assert check_prices("₹250 per 100", {25_000}) == []
    assert check_prices("two hundred fifty rupees", {25_000}) != []  # spelled out is never trusted
