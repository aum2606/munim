from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.db.models.quote import QuoteStatus
from app.schemas.knowledge import StrictModel
from app.schemas.pricing import Paise, Quantity, Totals
from app.schemas.requirements import SlotUpdate


class QuoteCandidate(StrictModel):
    sku: str
    name: str
    aliases: list[str]
    unit: str
    attributes: list[SlotUpdate]


class QuotationInput(StrictModel):
    category: str
    requirements: list[SlotUpdate]
    candidates: list[QuoteCandidate]


class ProposedLine(StrictModel):
    sku: str | None
    qty: str = Field(pattern=r"^\d{1,7}(?:\.\d{1,3})?$")
    options: list[SlotUpdate] = Field(max_length=20)


class QuotationOutput(StrictModel):
    lines: list[ProposedLine] = Field(max_length=20)
    unmapped_requirements: list[str] = Field(max_length=20)


class QuoteLineInput(Quantity):
    sku: str = Field(min_length=1, max_length=100)
    options: dict[str, str] = Field(default_factory=dict, max_length=20)
    discount_paise: Paise = 0


class QuoteEdit(StrictModel):
    expected_version: int = Field(strict=True, ge=1)
    lines: list[QuoteLineInput] = Field(min_length=1, max_length=20)
    customer_state: str | None = Field(default=None, pattern=r"^(0[1-9]|[12]\d|3[0-8])$")
    discount_paise: Paise = 0


class QuoteAction(StrictModel):
    expected_version: int = Field(strict=True, ge=1)


class QuoteLineView(StrictModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sku: str | None
    description: str
    qty: Decimal
    unit: str
    unit_price_paise: int
    addon_paise: int
    discount_paise: int
    gst_rate: int
    hsn_sac: str
    line_total_paise: int
    needs_owner_pricing: bool
    options: dict[str, str]


class Seller(StrictModel):
    name: str
    address: str
    gstin: str
    state_code: str | None
    logo_path: str | None


class QuoteView(StrictModel):
    id: UUID
    quote_number: str
    conversation_id: UUID
    status: QuoteStatus
    version: int
    seller: Seller
    customer_label: str
    customer_state: str | None
    created_at: datetime
    valid_until: datetime
    terms: str
    lines: list[QuoteLineView]
    totals: Totals
    display_total: str
    display_amounts: dict[str, str]
    display_lines: list[dict[str, str]]
    approved_by: UUID | None
    sent_at: datetime | None


class QuoteSettings(StrictModel):
    model_config = ConfigDict(from_attributes=True)
    auto_send_quotes: bool = False
    auto_send_limit_paise: Paise = 0
    quote_validity_days: int = Field(strict=True, ge=1, le=90, default=7)
    quote_terms: str = Field(
        default="Prices are valid until the stated date. Work starts after confirmation.",
        max_length=4000,
    )
