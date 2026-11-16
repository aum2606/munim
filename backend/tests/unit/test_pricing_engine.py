import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.pricing.engine import (
    Addon,
    LineInput,
    PricedLine,
    PricingRules,
    QtyTier,
    line_amount,
    price_line,
    quote_totals,
    tier_unit_price,
    to_paise,
)
from app.pricing.gst import gst_split, is_valid_gstin, state_code_of
from app.pricing.inr import amount_in_words
from app.pricing.quote_number import fiscal_year, format_quote_number

D = Decimal


def make_line(qty: str = "5", price: int = 25000, gst: int = 18, **kw: object) -> LineInput:
    return LineInput("Visiting card", "per 100", price, gst, D(qty), **kw)  # type: ignore[arg-type]


def test_a_plain_line_is_qty_times_unit_price() -> None:
    (only,) = price_line(make_line("5"), PricingRules()).lines
    assert (only.unit_price_paise, only.line_total_paise, only.discount_paise) == (25000, 125000, 0)


def test_fractional_quantities_round_half_up_to_the_paisa() -> None:
    assert price_line(make_line("2.5", 1800), PricingRules()).lines[0].line_total_paise == 4500
    assert to_paise(D("0.5")) == 1 and to_paise(D("0.49")) == 0 and to_paise(D("1.5")) == 2


def test_the_highest_applicable_tier_wins_with_a_fixed_price() -> None:
    tiers = (QtyTier(D(5), 23000), QtyTier(D(10), 21000), QtyTier(D(20), 20000))
    assert tier_unit_price(25000, D(4), tiers) == 25000  # below every tier: base price
    assert tier_unit_price(25000, D(5), tiers) == 23000  # a tier starts AT its minimum
    assert tier_unit_price(25000, D(15), tiers) == 21000
    assert tier_unit_price(25000, D(500), tiers) == 20000


def test_a_percentage_tier_is_taken_off_the_base_price() -> None:
    tiers = (QtyTier(D(10), discount_pct=D("12.5")),)
    assert tier_unit_price(1000, D(10), tiers) == 875
    assert tier_unit_price(999, D(10), tiers) == 874  # 874.125 rounds to 874
    assert tier_unit_price(1000, D(9), tiers) == 1000


def test_tiers_must_define_exactly_one_price_rule() -> None:
    with pytest.raises(ValueError):
        QtyTier(D(1))
    with pytest.raises(ValueError):
        QtyTier(D(1), 100, D(5))
    with pytest.raises(ValueError):
        QtyTier(D(1), discount_pct=D(101))
    with pytest.raises(ValueError):
        QtyTier(D(1), discount_pct=D(-1))


def test_addons_are_separate_lines_priced_per_unit_or_once() -> None:
    rules = PricingRules(
        addons=(Addon("LAM", "Matt lamination", 4500), Addon("SETUP", "Setup fee", 30000, False))
    )
    result = price_line(make_line("5", addon_codes=("LAM", "SETUP")), rules)
    base, lam, setup = result.lines
    assert (lam.description, lam.qty, lam.line_total_paise) == ("Matt lamination", D(5), 22500)
    assert (setup.qty, setup.unit, setup.line_total_paise) == (D(1), "each", 30000)
    assert base.line_total_paise == 125000 and result.violations == ()
    assert {x.gst_rate for x in result.lines} == {18}  # add-ons are taxed like the item


def test_unknown_addons_and_minimum_orders_are_reported_not_hidden() -> None:
    rules = PricingRules(min_qty=D(5), addons=(Addon("LAM", "Lamination", 100),))
    result = price_line(make_line("2", addon_codes=("LAM", "NOPE")), rules)
    assert any("minimum order is 5" in v for v in result.violations)
    assert any("unknown add-on 'NOPE'" in v for v in result.violations)
    assert len(result.lines) == 2  # still priced; the owner decides
    assert price_line(make_line("5"), rules).violations == ()  # exactly the minimum is fine


@pytest.mark.parametrize(
    "bad",
    [make_line("0"), make_line("-1"), make_line(price=-1), make_line(gst=7)],
)
def test_invalid_lines_are_refused(bad: LineInput) -> None:
    with pytest.raises(ValueError):
        price_line(bad, PricingRules())


def test_line_amount_checks_the_discount() -> None:
    assert line_amount(D(5), 25000, 5000) == 120000
    assert line_amount(D(5), 25000, 125000) == 0
    with pytest.raises(ValueError):
        line_amount(D(5), 25000, 125001)
    with pytest.raises(ValueError):
        line_amount(D(5), 25000, -1)


def _priced(total: int, gst: int, discount: int = 0) -> PricedLine:
    return PricedLine("x", "u", D(1), total + discount, discount, gst, None, uuid.uuid4(), total)


def test_intra_state_gst_splits_into_cgst_and_sgst() -> None:
    totals = quote_totals([_priced(140000, 18)], "24", "24")
    assert (totals.cgst_paise, totals.sgst_paise, totals.igst_paise) == (12600, 12600, 0)
    assert totals.total_paise == 165200 and totals.round_off_paise == 0


def test_unknown_state_is_treated_as_intra_state() -> None:
    assert quote_totals([_priced(10000, 18)], "24", None).igst_paise == 0
    assert quote_totals([_priced(10000, 18)], None, "27").igst_paise == 0


def test_inter_state_gst_is_igst_only() -> None:
    totals = quote_totals([_priced(140000, 18)], "24", "27")
    assert (totals.cgst_paise, totals.sgst_paise, totals.igst_paise) == (0, 0, 25200)
    assert totals.total_paise == 165200


def test_totals_group_by_rate_and_round_off_to_the_rupee() -> None:
    totals = quote_totals([_priced(10001, 12), _priced(5555, 18), _priced(999, 12)], "24", "24")
    assert [(g.gst_rate, g.taxable_paise) for g in totals.groups] == [(12, 11000), (18, 5555)]
    before = totals.taxable_paise + totals.cgst_paise + totals.sgst_paise + totals.igst_paise
    assert totals.total_paise % 100 == 0 and totals.total_paise == before + totals.round_off_paise
    assert abs(totals.round_off_paise) <= 50


def test_discounts_reduce_the_taxable_amount_before_gst() -> None:
    totals = quote_totals([_priced(90000, 18, discount=10000)], "24", "24")
    assert (totals.subtotal_paise, totals.discount_paise, totals.taxable_paise) == (
        100000,
        10000,
        90000,
    )
    assert totals.cgst_paise == 8100  # 9% of 900.00


def test_an_empty_quote_totals_to_zero() -> None:
    totals = quote_totals([], "24", "24")
    assert (totals.total_paise, totals.groups) == (0, ())


def test_round_off_rounds_half_up() -> None:
    assert quote_totals([_priced(50, 0)], "24", "24").total_paise == 100
    assert quote_totals([_priced(49, 0)], "24", "24").total_paise == 0


def test_printing_scenario_hand_calculated() -> None:
    """500 visiting cards (5 x 'per 100'), tier price Rs 235, matt lamination Rs 45 per 100."""
    rules = PricingRules(
        tiers=(QtyTier(D(5), 23500),), addons=(Addon("LAM", "Matt lamination", 4500),)
    )
    result = price_line(make_line("5", addon_codes=("LAM",)), rules)
    totals = quote_totals(result.lines, "24", "24")
    # 5 x 235 = 1,175 ; 5 x 45 = 225 ; taxable 1,400 ; GST 18% = 252 (126 + 126) ; total 1,652
    assert [x.line_total_paise for x in result.lines] == [117500, 22500]
    assert (totals.taxable_paise, totals.cgst_paise, totals.sgst_paise) == (140000, 12600, 12600)
    assert totals.total_paise == 165200


def test_gstin_and_state_helpers() -> None:
    assert is_valid_gstin("24ABCDE1234F1Z5") and state_code_of("24ABCDE1234F1Z5") == "24"
    for bad in ("", "24ABCDE1234F1Z", "99ABCDE1234F1Z5", "24abcde1234f1z5", "00ABCDE1234F1Z5"):
        assert not is_valid_gstin(bad)
    assert gst_split(100, 5, True) == (3, 3, 0) and gst_split(100, 5, False) == (0, 0, 5)


@pytest.mark.parametrize(
    ("paise", "words"),
    [
        (0, "Rupees Zero Only"),
        (5, "Rupees Zero and Five Paise Only"),
        (100, "Rupees One Only"),
        (165200, "Rupees One Thousand Six Hundred Fifty-Two Only"),
        (
            12345678,
            "Rupees One Lakh Twenty-Three Thousand Four Hundred Fifty-Six and Seventy-Eight"
            " Paise Only",
        ),
        (1000000000, "Rupees One Crore Only"),
        (10100000000, "Rupees Ten Crore Ten Lakh Only"),
        (2000000, "Rupees Twenty Thousand Only"),
        (110000000, "Rupees Eleven Lakh Only"),
        (1000100, "Rupees Ten Thousand One Only"),
    ],
)
def test_amount_in_words_uses_the_indian_system(paise: int, words: str) -> None:
    assert amount_in_words(paise) == words


def test_amount_in_words_rejects_negatives_and_handles_huge_crores() -> None:
    with pytest.raises(ValueError):
        amount_in_words(-1)
    assert amount_in_words(1_500_000_000_000) == "Rupees One Thousand Five Hundred Crore Only"


def test_fiscal_year_boundaries_and_numbers() -> None:
    assert fiscal_year(date(2026, 3, 31)) == "2025-26"
    assert fiscal_year(date(2026, 4, 1)) == "2026-27"
    assert fiscal_year(date(2026, 12, 31)) == "2026-27"
    assert fiscal_year(date(2099, 5, 1)) == "2099-00"
    assert format_quote_number("2026-27", 7) == "Q/2026-27/0007"
    assert format_quote_number("2026-27", 12345) == "Q/2026-27/12345"
