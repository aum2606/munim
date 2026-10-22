from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceRef(StrictModel):
    catalog_id: UUID
    sku: str
    paise: int = Field(strict=True, ge=0)
    formatted: str


class Fact(StrictModel):
    ref: str
    kind: Literal["catalog", "chunk", "business"]
    text: str
    price: PriceRef | None


class SearchResults(StrictModel):
    facts: list[Fact]
