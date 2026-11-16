import re
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator

from app.pricing.gst import is_valid_gstin, state_code_of
from app.schemas.auth import StrictRequest
from app.schemas.quote import STATE_CODE

_PHONE = re.compile(r"^\+?[\d\s-]{7,20}$")


class TenantProfile(BaseModel):
    id: uuid.UUID
    name: str
    business_type: str
    gstin: str | None
    state_code: str | None
    address: str | None
    phone: str | None
    quote_terms: str | None
    quote_validity_days: int


class TenantProfileUpdate(StrictRequest):
    """Only the fields you send are changed; send null to clear one."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    business_type: str | None = Field(default=None, min_length=1, max_length=60)
    gstin: str | None = None
    state_code: str | None = None
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = None
    quote_terms: str | None = Field(default=None, max_length=2000)
    quote_validity_days: int | None = Field(default=None, ge=1, le=90)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not is_valid_gstin(value):
            raise ValueError("That does not look like a valid GSTIN")
        return value

    @field_validator("state_code")
    @classmethod
    def _state(cls, value: str | None) -> str | None:
        if value is not None and not STATE_CODE.match(value):
            raise ValueError("state_code must be a 2-digit GST state code")
        return value

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if value is not None and not _PHONE.match(value):
            raise ValueError("That does not look like a phone number")
        return value

    @model_validator(mode="after")
    def _state_matches_gstin(self) -> "TenantProfileUpdate":
        if self.gstin and self.state_code and state_code_of(self.gstin) != self.state_code:
            raise ValueError("The GSTIN starts with a different state code")
        return self
