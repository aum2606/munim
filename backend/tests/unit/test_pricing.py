from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.errors import DomainError
from app.pricing.engine import price_line, quote_totals
from app.schemas.pricing import PriceItem, Quantity, Rule


def rule(kind, **params):
    return TypeAdapter(Rule).validate_python({"rule_type": kind, **params})


def line(price=45000, qty=1, rate=18, rules=None, options=None, discount=0):
    return price_line(
        PriceItem(base_price_paise=price, gst_rate=rate),
        Decimal(qty),
        options or {},
        rules or [],
        discount,
    )


def test_tiers_addons_seasonal_and_line_discount_order():
    rules = [
        rule(
            "qty_tier",
            tiers=[
                {"min_qty": 5, "unit_price_paise": 40000},
                {"min_qty": 10, "unit_price_paise": 35000},
            ],
        ),
        rule("addon", option="sides", value="double-sided", amount_paise=10000, per_unit=True),
        rule("addon", option="delivery", value="yes", amount_paise=5000, per_unit=False),
        rule("seasonal", basis_points=11000),
        rule("min_order", minimum_qty=1),
    ]
    result = line(
        qty=5, rules=rules, options={"sides": "double-sided", "delivery": "yes"}, discount=1000
    )
    assert result.unit_price_paise == 44000 and result.addon_paise == 55000
    assert result.subtotal_paise == 275000 and result.taxable_paise == 274000
    assert line(qty=2, rules=rules).unit_price_paise == 49500
    assert line(qty=10, rules=rules).unit_price_paise == 38500
    with pytest.raises(DomainError, match="Minimum"):
        line(qty=1, rules=[rule("min_order", minimum_qty=2)])
    with pytest.raises(DomainError, match="discount"):
        line(discount=45001)


def test_intra_inter_state_grouped_gst_discount_allocation_and_roundoff():
    lines = [line(price=10000, rate=18), line(price=10000, rate=5)]
    intra = quote_totals(lines, "24", "24", 1001)
    assert intra.subtotal_paise == 20000 and intra.discount_paise == 1001
    assert [g.taxable_paise for g in intra.tax_groups] == [9500, 9499]
    assert (intra.cgst_paise, intra.sgst_paise, intra.igst_paise) == (1093, 1093, 0)
    assert intra.total_paise == 21200 and intra.round_off_paise == 15
    inter = quote_totals([line(price=10000)], "24", "27")
    assert (inter.cgst_paise, inter.sgst_paise, inter.igst_paise, inter.total_paise) == (
        0,
        0,
        1800,
        11800,
    )
    assert quote_totals([line(price=10001)], "24", None).round_off_paise == -1
    assert quote_totals([line(price=10050, rate=0)], None, None).round_off_paise == 50
    assert (
        quote_totals([line(price=0, rate=0), line(price=0, rate=18)], "24", None).total_paise == 0
    )
    assert quote_totals([line(price=10000, discount=500)], "24", None, 500).discount_paise == 1000
    with pytest.raises(DomainError):
        quote_totals([], "24", None)
    with pytest.raises(DomainError):
        quote_totals([line(price=0)], "24", None, 1)


@pytest.mark.parametrize("qty", [0, -1, "1.0001", "1000001", "NaN", "Infinity", True])
def test_invalid_or_inexact_quantity_rejected(qty):
    with pytest.raises(ValidationError):
        Quantity(qty=qty)


def test_fractional_quantity_exact_paise_limits_and_money_validation():
    assert line(price=101, qty="1.5").subtotal_paise == 152
    with pytest.raises(ValidationError):
        line(price=-1)
    with pytest.raises(ValidationError):
        line(discount=-1)
    with pytest.raises(ValidationError):
        line(price=9_000_000_000_000_000, qty=2)
    with pytest.raises(ValidationError):
        quote_totals([line(price=9_000_000_000_000_000)], "24", None)
