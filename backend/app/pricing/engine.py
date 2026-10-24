from decimal import ROUND_DOWN, Decimal

from pydantic import TypeAdapter

from app.core.errors import DomainError
from app.pricing.gst import gst_split, paise_round
from app.schemas.pricing import (
    AddonRule,
    GSTRate,
    LineResult,
    MinimumRule,
    Paise,
    PriceItem,
    Quantity,
    QuantityTierRule,
    Rule,
    SeasonalRule,
    TaxGroup,
    Totals,
)


def price_line(
    item: PriceItem,
    qty: Decimal,
    options: dict[str, str],
    rules: list[Rule],
    discount_paise: int = 0,
) -> LineResult:
    quantity = Quantity(qty=qty).qty
    discount = TypeAdapter(Paise).validate_python(discount_paise)
    unit_price = item.base_price_paise
    addons = Decimal(0)
    for rule in rules:
        if isinstance(rule, MinimumRule) and quantity < rule.minimum_qty:
            raise DomainError(f"Minimum order quantity is {rule.minimum_qty}")
        if isinstance(rule, QuantityTierRule):
            tiers = [tier for tier in rule.tiers if quantity >= tier.min_qty]
            if tiers:
                unit_price = max(tiers, key=lambda tier: tier.min_qty).unit_price_paise
    for rule in rules:
        if isinstance(rule, SeasonalRule):
            unit_price = paise_round(
                Decimal(unit_price) * Decimal(rule.basis_points) / Decimal(10_000)
            )
        if isinstance(rule, AddonRule) and options.get(rule.option) == rule.value:
            addons += Decimal(rule.amount_paise) * (quantity if rule.per_unit else Decimal(1))
    addon_paise = paise_round(addons)
    subtotal = paise_round(Decimal(unit_price) * quantity) + addon_paise
    TypeAdapter(Paise).validate_python(subtotal)
    if discount > subtotal:
        raise DomainError("Line discount exceeds its value")
    return LineResult(
        qty=quantity,
        unit_price_paise=unit_price,
        addon_paise=addon_paise,
        subtotal_paise=subtotal,
        discount_paise=discount,
        taxable_paise=subtotal - discount,
        gst_rate=item.gst_rate,
    )


def quote_totals(
    lines: list[LineResult],
    tenant_state: str | None,
    customer_state: str | None,
    discount_paise: int = 0,
) -> Totals:
    discount = TypeAdapter(Paise).validate_python(discount_paise)
    if not lines:
        raise DomainError("A quote needs at least one line")
    taxable = sum(line.taxable_paise for line in lines)
    if discount > taxable:
        raise DomainError("Quote discount exceeds its value")
    buckets: dict[GSTRate, int] = {}
    for line in lines:
        buckets[line.gst_rate] = buckets.get(line.gst_rate, 0) + line.taxable_paise
    remaining = discount
    groups: list[TaxGroup] = []
    for index, (rate, base) in enumerate(sorted(buckets.items())):
        if index == len(buckets) - 1:
            share = remaining
        else:
            share = int(
                (Decimal(discount) * Decimal(base) / Decimal(max(taxable, 1))).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
        remaining -= share
        base -= share
        cgst, sgst, igst = gst_split(
            base, rate, bool(customer_state and customer_state != tenant_state)
        )
        groups.append(
            TaxGroup(
                gst_rate=rate, taxable_paise=base, cgst_paise=cgst, sgst_paise=sgst, igst_paise=igst
            )
        )
    cgst = sum(group.cgst_paise for group in groups)
    sgst = sum(group.sgst_paise for group in groups)
    igst = sum(group.igst_paise for group in groups)
    unrounded = taxable - discount + cgst + sgst + igst
    total = paise_round(Decimal(unrounded) / Decimal(100)) * 100
    TypeAdapter(Paise).validate_python(total)
    return Totals(
        quote_discount_paise=discount,
        subtotal_paise=sum(line.subtotal_paise for line in lines),
        discount_paise=discount + sum(line.discount_paise for line in lines),
        taxable_paise=taxable - discount,
        cgst_paise=cgst,
        sgst_paise=sgst,
        igst_paise=igst,
        round_off_paise=total - unrounded,
        total_paise=total,
        tax_groups=groups,
    )
