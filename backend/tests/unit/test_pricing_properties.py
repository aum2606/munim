"""Property tests: whatever the inputs, the totals always add up."""

import uuid
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.pricing.engine import PricedLine, QtyTier, quote_totals, tier_unit_price
from app.pricing.gst import GST_RATES

money = st.integers(min_value=0, max_value=10**9)
states = st.sampled_from(["24", "27", "07", None])

lines = st.builds(
    lambda total, discount, rate: PricedLine(
        "x", "u", Decimal(1), total + discount, discount, rate, None, uuid.uuid4(), total
    ),
    total=money,
    discount=money,
    rate=st.sampled_from(GST_RATES),
)


@given(st.lists(lines, max_size=12), states, states)
def test_totals_always_add_up(
    items: list[PricedLine], seller: str | None, buyer: str | None
) -> None:
    totals = quote_totals(items, seller, buyer)
    taxable = sum(i.line_total_paise for i in items)
    tax = totals.cgst_paise + totals.sgst_paise + totals.igst_paise
    assert totals.taxable_paise == taxable
    assert totals.subtotal_paise - totals.discount_paise == taxable
    assert totals.total_paise == taxable + tax + totals.round_off_paise
    assert totals.total_paise % 100 == 0  # always a whole rupee
    assert abs(totals.round_off_paise) <= 50
    assert min(totals.cgst_paise, totals.sgst_paise, totals.igst_paise, totals.total_paise) >= 0


@given(st.lists(lines, min_size=1, max_size=8))
def test_intra_and_inter_state_tax_agree_within_a_paisa_per_rate(items: list[PricedLine]) -> None:
    intra = quote_totals(items, "24", "24")
    inter = quote_totals(items, "24", "27")
    assert intra.igst_paise == 0 and inter.cgst_paise == inter.sgst_paise == 0
    assert intra.cgst_paise == intra.sgst_paise
    assert abs((intra.cgst_paise + intra.sgst_paise) - inter.igst_paise) <= len(intra.groups)


@given(
    base=st.integers(min_value=1, max_value=10**7),
    cuts=st.lists(st.integers(min_value=0, max_value=100), min_size=1, max_size=5, unique=True),
    q1=st.integers(min_value=1, max_value=10_000),
    q2=st.integers(min_value=1, max_value=10_000),
)
def test_more_quantity_never_raises_the_unit_price(
    base: int, cuts: list[int], q1: int, q2: int
) -> None:
    # tiers whose discounts grow with quantity, as in a real price list
    tiers = tuple(
        QtyTier(Decimal((i + 1) * 10), discount_pct=Decimal(pct))
        for i, pct in enumerate(sorted(cuts))
    )
    low, high = sorted((q1, q2))
    assert tier_unit_price(base, Decimal(high), tiers) <= tier_unit_price(base, Decimal(low), tiers)
    assert 0 <= tier_unit_price(base, Decimal(high), tiers) <= base
