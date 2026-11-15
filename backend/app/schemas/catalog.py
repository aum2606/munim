import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import StockStatus
from app.schemas.auth import StrictRequest

GST_RATES = (0, 5, 12, 18, 28)


class ColumnMapping(BaseModel):
    """What the LLM column mapper must return."""

    mapping: dict[str, str]


class ImportRowPreview(BaseModel):
    row: int  # 1-based spreadsheet row number (header is row 1)
    values: dict[str, Any]
    errors: list[str]


class ImportPreview(BaseModel):
    job_id: uuid.UUID
    filename: str
    status: str
    headers: list[str]
    mapping: dict[str, str]
    missing_required: list[str]
    row_count: int
    valid_count: int
    error_count: int
    rows: list[ImportRowPreview]  # first rows, with their problems


class ImportMappingUpdate(StrictRequest):
    mapping: dict[str, str]


class ImportCommitResult(BaseModel):
    created: int
    updated: int
    skipped: int


class CatalogItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    aliases: list[str]
    category: str | None
    description: str | None
    unit: str
    base_price_paise: int
    gst_rate: int
    hsn_sac: str | None
    stock_status: StockStatus
    is_active: bool


def _check_gst(value: int | None) -> int | None:
    if value is not None and value not in GST_RATES:
        raise ValueError(f"gst_rate must be one of {', '.join(map(str, GST_RATES))}")
    return value


class CatalogItemCreate(StrictRequest):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    base_price_paise: int = Field(ge=0, le=10**12)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    unit: str = Field(default="unit", min_length=1, max_length=24)
    gst_rate: int = 18
    hsn_sac: str | None = Field(default=None, max_length=16)
    stock_status: StockStatus = StockStatus.NA

    _gst = field_validator("gst_rate")(_check_gst)


class CatalogItemUpdate(StrictRequest):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_price_paise: int | None = Field(default=None, ge=0, le=10**12)
    aliases: list[str] | None = Field(default=None, max_length=20)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, min_length=1, max_length=24)
    gst_rate: int | None = None
    hsn_sac: str | None = Field(default=None, max_length=16)
    stock_status: StockStatus | None = None
    is_active: bool | None = None

    _gst = field_validator("gst_rate")(_check_gst)
