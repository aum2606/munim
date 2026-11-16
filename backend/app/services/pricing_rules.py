from collections.abc import Sequence
from decimal import Decimal

from app.db.models import PricingRule, RuleType
from app.pricing.engine import Addon, PricingRules, QtyTier


def build_rules(rows: Sequence[PricingRule]) -> PricingRules:
    """Turn stored rules into the engine's input. Rules were validated when they were saved."""
    tiers: list[QtyTier] = []
    addons: dict[str, Addon] = {}
    min_qty: Decimal | None = None
    for row in rows:
        params = row.params
        if row.rule_type == RuleType.QTY_TIER:
            for tier in params["tiers"]:
                pct = tier.get("discount_pct")
                tiers.append(
                    QtyTier(
                        Decimal(str(tier["min_qty"])),
                        unit_price_paise=tier.get("unit_price_paise"),
                        discount_pct=None if pct is None else Decimal(str(pct)),
                    )
                )
        elif row.rule_type == RuleType.ADDON:
            addons[params["code"]] = Addon(
                params["code"], params["name"], int(params["price_paise"]), bool(params["per_unit"])
            )
        else:
            minimum = Decimal(str(params["min_qty"]))
            min_qty = minimum if min_qty is None else max(min_qty, minimum)
    return PricingRules(tuple(tiers), tuple(addons.values()), min_qty)
