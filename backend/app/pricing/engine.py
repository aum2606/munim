"""The pricing engine: the ONLY code that turns quantities and catalogue prices into amounts.

Pure functions over integer paise and Decimal quantities. No floats, no database, no model.
Order of rules for a line (BUILD_PLAN.md section 9): base price, quantity tier, add-ons,
line discount, then GST.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.pricing.gst import GST_RATES, gst_split

_HUNDRED = Decimal(100)


def to_paise(amount: Decimal) -> int:
    """Round a Decimal number of paise to a whole paisa, halves up."""
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class QtyTier:
    """From min_qty upward, either a fixed unit price or a percentage off the base price."""

    min_qty: Decimal
    unit_price_paise: int | None = None
    discount_pct: Decimal | None = None

    def __post_init__(self) -> None:
        if (self.unit_price_paise is None) == (self.discount_pct is None):
            raise ValueError("a tier needs exactly one of unit_price_paise or discount_pct")
        if self.discount_pct is not None and not Decimal(0) <= self.discount_pct <= _HUNDRED:
            raise ValueError("discount_pct must be between 0 and 100")


@dataclass(frozen=True)
class Addon:
    code: str
    name: str
    price_paise: int
    per_unit: bool = True  # False: charged once per line, whatever the quantity


@dataclass(frozen=True)
class PricingRules:
    tiers: tuple[QtyTier, ...] = ()
    addons: tuple[Addon, ...] = ()
    min_qty: Decimal | None = None


@dataclass(frozen=True)
class LineInput:
    description: str
    unit: str
    base_price_paise: int
    gst_rate: int
    qty: Decimal
    hsn_sac: str | None = None
    catalog_item_id: uuid.UUID | None = None
    addon_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PricedLine:
    description: str
    unit: str
    qty: Decimal
    unit_price_paise: int
    discount_paise: int
    gst_rate: int
    hsn_sac: str | None
    catalog_item_id: uuid.UUID | None
    line_total_paise: int  # before tax, after discount

    @property
    def gross_paise(self) -> int:
        return self.line_total_paise + self.discount_paise


@dataclass(frozen=True)
class PricedResult:
    lines: tuple[PricedLine, ...]  # the item first, then one line per add-on
    violations: tuple[str, ...]  # rule problems the owner should see; never silently "fixed"


def line_amount(qty: Decimal, unit_price_paise: int, discount_paise: int = 0) -> int:
    """qty x unit price, less a discount. Raises if the discount exceeds the amount."""
    gross = to_paise(qty * unit_price_paise)
    if not 0 <= discount_paise <= gross:
        raise ValueError("discount must be between zero and the line amount")
    return gross - discount_paise


def _check_input(inp: LineInput) -> None:
    if inp.qty <= 0:
        raise ValueError("quantity must be greater than zero")
    if inp.base_price_paise < 0:
        raise ValueError("price must not be negative")
    if inp.gst_rate not in GST_RATES:
        raise ValueError(f"GST rate must be one of {GST_RATES}")


def tier_unit_price(base_price_paise: int, qty: Decimal, tiers: Sequence[QtyTier]) -> int:
    """The unit price at this quantity: the tier with the highest min_qty not above qty."""
    eligible = [t for t in tiers if t.min_qty <= qty]
    if not eligible:
        return base_price_paise
    best = max(eligible, key=lambda t: t.min_qty)
    if best.unit_price_paise is not None:
        return best.unit_price_paise
    assert best.discount_pct is not None  # guaranteed by QtyTier
    return to_paise(Decimal(base_price_paise) * (_HUNDRED - best.discount_pct) / _HUNDRED)


def price_line(inp: LineInput, rules: PricingRules) -> PricedResult:
    _check_input(inp)
    violations: list[str] = []
    if rules.min_qty is not None and inp.qty < rules.min_qty:
        violations.append(f"minimum order is {rules.min_qty} {inp.unit}")

    unit_price = tier_unit_price(inp.base_price_paise, inp.qty, rules.tiers)
    lines = [
        PricedLine(
            description=inp.description,
            unit=inp.unit,
            qty=inp.qty,
            unit_price_paise=unit_price,
            discount_paise=0,
            gst_rate=inp.gst_rate,
            hsn_sac=inp.hsn_sac,
            catalog_item_id=inp.catalog_item_id,
            line_total_paise=line_amount(inp.qty, unit_price),
        )
    ]
    known = {a.code: a for a in rules.addons}
    for code in inp.addon_codes:
        addon = known.get(code)
        if addon is None:
            violations.append(f"unknown add-on {code!r}")
            continue
        addon_qty = inp.qty if addon.per_unit else Decimal(1)
        lines.append(
            PricedLine(
                description=addon.name,
                unit=inp.unit if addon.per_unit else "each",
                qty=addon_qty,
                unit_price_paise=addon.price_paise,
                discount_paise=0,
                gst_rate=inp.gst_rate,
                hsn_sac=inp.hsn_sac,
                catalog_item_id=None,
                line_total_paise=line_amount(addon_qty, addon.price_paise),
            )
        )
    return PricedResult(tuple(lines), tuple(violations))


@dataclass(frozen=True)
class TaxGroup:
    gst_rate: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int


@dataclass(frozen=True)
class Totals:
    subtotal_paise: int  # before discounts
    discount_paise: int
    taxable_paise: int
    groups: tuple[TaxGroup, ...]  # one per GST rate, ascending
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    round_off_paise: int
    total_paise: int


def quote_totals(
    lines: Sequence[PricedLine], seller_state: str | None, buyer_state: str | None
) -> Totals:
    """Totals with GST. Same state, or either state unknown, means CGST + SGST; else IGST."""
    intra_state = seller_state is None or buyer_state is None or seller_state == buyer_state
    taxable_by_rate: dict[int, int] = {}
    for line in lines:
        taxable_by_rate[line.gst_rate] = (
            taxable_by_rate.get(line.gst_rate, 0) + line.line_total_paise
        )

    groups = []
    for rate in sorted(taxable_by_rate):
        cgst, sgst, igst = gst_split(taxable_by_rate[rate], rate, intra_state)
        groups.append(TaxGroup(rate, taxable_by_rate[rate], cgst, sgst, igst))

    subtotal = sum(line.gross_paise for line in lines)
    discount = sum(line.discount_paise for line in lines)
    taxable = subtotal - discount
    cgst = sum(g.cgst_paise for g in groups)
    sgst = sum(g.sgst_paise for g in groups)
    igst = sum(g.igst_paise for g in groups)
    before_round = taxable + cgst + sgst + igst
    total = to_paise(Decimal(before_round) / _HUNDRED) * 100  # nearest whole rupee
    return Totals(
        subtotal_paise=subtotal,
        discount_paise=discount,
        taxable_paise=taxable,
        groups=tuple(groups),
        cgst_paise=cgst,
        sgst_paise=sgst,
        igst_paise=igst,
        round_off_paise=total - before_round,
        total_paise=total,
    )
