from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.knowledge import StrictModel

Paise = Annotated[int, Field(strict=True, ge=0, le=9_000_000_000_000_000)]
GSTRate = Literal[0, 5, 12, 18, 28]


class Tier(StrictModel):
    min_qty: int = Field(strict=True, ge=1, le=1_000_000)
    unit_price_paise: Paise


class QuantityTierRule(StrictModel):
    rule_type: Literal["qty_tier"]
    tiers: list[Tier] = Field(min_length=1, max_length=20)


class AddonRule(StrictModel):
    rule_type: Literal["addon"]
    option: str = Field(min_length=1, max_length=50)
    value: str = Field(min_length=1, max_length=100)
    amount_paise: Paise
    per_unit: bool


class MinimumRule(StrictModel):
    rule_type: Literal["min_order"]
    minimum_qty: int = Field(strict=True, ge=1, le=1_000_000)


class SeasonalRule(StrictModel):
    rule_type: Literal["seasonal"]
    basis_points: int = Field(strict=True, ge=0, le=100_000)


Rule = Annotated[
    QuantityTierRule | AddonRule | MinimumRule | SeasonalRule, Field(discriminator="rule_type")
]


class PricingRuleInput(StrictModel):
    catalog_item_id: UUID | None = None
    category: str | None = Field(default=None, max_length=100)
    rule: Rule
    priority: int = Field(default=0, strict=True, ge=0, le=1000)
    active_from: datetime | None = None
    active_to: datetime | None = None

    @model_validator(mode="after")
    def valid_window(self) -> "PricingRuleInput":
        if any(
            value is not None and value.tzinfo is None
            for value in (self.active_from, self.active_to)
        ):
            raise ValueError("Rule dates require a timezone")
        if self.active_from and self.active_to and self.active_from > self.active_to:
            raise ValueError("Rule start must precede end")
        return self


class PriceItem(StrictModel):
    base_price_paise: Paise
    gst_rate: GSTRate


class Quantity(StrictModel):
    qty: Decimal = Field(gt=0, le=1_000_000, max_digits=10, decimal_places=3)

    @field_validator("qty", mode="before")
    @classmethod
    def exact_quantity(cls, value: Any) -> Any:
        if isinstance(value, (float, bool)):
            raise ValueError("Use an integer or decimal string for quantity")
        return value


class LineResult(StrictModel):
    qty: Decimal
    unit_price_paise: int
    addon_paise: int
    subtotal_paise: int
    discount_paise: int
    taxable_paise: int
    gst_rate: GSTRate


class TaxGroup(StrictModel):
    gst_rate: GSTRate
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int


class Totals(StrictModel):
    quote_discount_paise: int = 0
    subtotal_paise: int
    discount_paise: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    round_off_paise: int
    total_paise: int
    tax_groups: list[TaxGroup]
