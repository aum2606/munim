import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import QuoteStatus, RuleType
from app.schemas.auth import StrictRequest

STATE_CODE = re.compile(r"^(0[1-9]|[12]\d|3[0-8])$")
SLOT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
SLOT_TYPES = {"string", "integer", "number", "array"}


class QuoteItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    description: str
    qty: Decimal
    unit: str
    unit_price_paise: int
    discount_paise: int
    gst_rate: int
    hsn_sac: str | None
    line_total_paise: int
    needs_owner_pricing: bool


class TaxGroupOut(BaseModel):
    gst_rate: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int


class QuoteSummary(BaseModel):
    id: uuid.UUID
    quote_number: str
    status: QuoteStatus
    total_paise: int
    valid_until: date
    customer_name: str | None
    unpriced_lines: int
    created_at: datetime


class QuoteDetail(BaseModel):
    id: uuid.UUID
    quote_number: str
    status: QuoteStatus
    customer_name: str | None
    valid_until: date
    buyer_state_code: str | None
    subtotal_paise: int
    discount_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    round_off_paise: int
    total_paise: int
    items: list[QuoteItemOut]
    tax_groups: list[TaxGroupOut]
    sent_at: datetime | None
    created_at: datetime


class LineEditIn(StrictRequest):
    id: uuid.UUID
    qty: Decimal | None = Field(default=None, gt=0, le=10_000_000, decimal_places=3)
    unit_price_paise: int | None = Field(default=None, ge=0, le=10**10)
    discount_paise: int | None = Field(default=None, ge=0, le=10**10)


class QuoteUpdate(StrictRequest):
    items: list[LineEditIn] = Field(default_factory=list, max_length=100)
    buyer_state_code: str | None = None  # send null to clear it

    @field_validator("buyer_state_code")
    @classmethod
    def _valid_state(cls, value: str | None) -> str | None:
        if value is not None and not STATE_CODE.match(value):
            raise ValueError("buyer_state_code must be a 2-digit GST state code")
        return value


# --- pricing rules ---------------------------------------------------------------------------


class TierIn(StrictRequest):
    min_qty: Decimal = Field(gt=0, le=10_000_000)
    unit_price_paise: int | None = Field(default=None, ge=0, le=10**10)
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _one_price_rule(self) -> "TierIn":
        if (self.unit_price_paise is None) == (self.discount_pct is None):
            raise ValueError("give either unit_price_paise or discount_pct, not both")
        return self


class AddonIn(StrictRequest):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    name: str = Field(min_length=1, max_length=100)
    price_paise: int = Field(ge=0, le=10**10)
    per_unit: bool = True


class RuleCreate(StrictRequest):
    rule_type: RuleType
    catalog_item_id: uuid.UUID | None = None
    category: str | None = Field(default=None, max_length=80)
    tiers: list[TierIn] | None = Field(default=None, min_length=1, max_length=20)
    addon: AddonIn | None = None
    min_qty: Decimal | None = Field(default=None, gt=0, le=10_000_000)

    @model_validator(mode="after")
    def _matches_type(self) -> "RuleCreate":
        if (self.catalog_item_id is None) == (self.category is None):
            raise ValueError("give either catalog_item_id or category")
        expected = {
            RuleType.QTY_TIER: self.tiers,
            RuleType.ADDON: self.addon,
            RuleType.MIN_ORDER: self.min_qty,
        }
        if expected[self.rule_type] is None:
            raise ValueError(f"{self.rule_type.value} rules need their own details")
        if sum(v is not None for v in (self.tiers, self.addon, self.min_qty)) != 1:
            raise ValueError("give details for one rule type only")
        return self

    def params(self) -> dict[str, Any]:
        if self.rule_type == RuleType.QTY_TIER:
            assert self.tiers is not None
            return {
                "tiers": [
                    {
                        "min_qty": str(t.min_qty),
                        "unit_price_paise": t.unit_price_paise,
                        "discount_pct": None if t.discount_pct is None else str(t.discount_pct),
                    }
                    for t in self.tiers
                ]
            }
        if self.rule_type == RuleType.ADDON:
            assert self.addon is not None
            return self.addon.model_dump()
        return {"min_qty": str(self.min_qty)}


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_type: RuleType
    catalog_item_id: uuid.UUID | None
    category: str | None
    params: dict[str, Any]
    is_active: bool


# --- requirement schemas ----------------------------------------------------------------------


class RequirementSchemaIn(StrictRequest):
    json_schema: dict[str, Any]
    defaults: dict[str, Any] = Field(default_factory=dict)
    question_hints: dict[str, str] = Field(default_factory=dict)

    @field_validator("json_schema")
    @classmethod
    def _valid_schema(cls, schema: dict[str, Any]) -> dict[str, Any]:
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not 1 <= len(properties) <= 30:
            raise ValueError("json_schema.properties must list 1 to 30 details")
        for name, definition in properties.items():
            if not SLOT_NAME.match(name) or not isinstance(definition, dict):
                raise ValueError(f"invalid detail name {name!r}")
            if definition.get("type", "string") not in SLOT_TYPES:
                raise ValueError(f"{name}: type must be one of {sorted(SLOT_TYPES)}")
        required = schema.get("required", [])
        if not isinstance(required, list) or any(r not in properties for r in required):
            raise ValueError("json_schema.required must name listed details")
        return {k: schema[k] for k in ("properties", "required") if k in schema}


class RequirementSchemaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str
    json_schema: dict[str, Any]
    defaults: dict[str, Any]
    question_hints: dict[str, str]
