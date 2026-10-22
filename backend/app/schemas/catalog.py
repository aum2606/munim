from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.db.models.knowledge import StockStatus
from app.pricing.inr import format_inr


class CatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    category: str = Field(default="general", min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    unit: str = Field(default="piece", min_length=1, max_length=100)
    base_price_paise: int = Field(strict=True, ge=0, le=9223372036854775807)
    gst_rate: Annotated[int, Field(strict=True)] = 18
    hsn_sac: str = Field(default="", max_length=20)
    stock_status: StockStatus = StockStatus.NA
    attributes: dict[str, str] = Field(default_factory=dict)
    is_active: bool = True

    @field_validator("gst_rate")
    @classmethod
    def valid_gst(cls, rate: int) -> int:
        if rate not in {0, 5, 12, 18, 28}:
            raise ValueError("Unsupported GST rate")
        return rate


class CatalogView(CatalogInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID

    @computed_field  # type: ignore[prop-decorator]  # Pydantic property wrapper.
    @property
    def display_price(self) -> str:
        return format_inr(self.base_price_paise)


class ColumnBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    column: str


class MappingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bindings: list[ColumnBinding]


class MappingInput(BaseModel):
    headers: list[str]


class ImportCommit(BaseModel):
    mapping: dict[str, str]


class ImportRow(BaseModel):
    number: int
    catalog: CatalogInput | None
    errors: list[str]

    @computed_field  # type: ignore[prop-decorator]  # Pydantic property wrapper.
    @property
    def display_price(self) -> str | None:
        return format_inr(self.catalog.base_price_paise) if self.catalog is not None else None


class ImportView(BaseModel):
    id: UUID
    headers: list[str]
    mapping: dict[str, str]
    rows: list[ImportRow]
    committed: bool
