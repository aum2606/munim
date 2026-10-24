from pydantic import ConfigDict, Field, model_validator

from app.schemas.knowledge import StrictModel


class QuoteProfile(StrictModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    gstin: str | None = Field(default=None, pattern=r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]$")
    state_code: str | None = Field(default=None, pattern=r"^(0[1-9]|[12]\d|3[0-8])$")
    address: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def consistent_state(self) -> "QuoteProfile":
        if self.gstin and self.state_code and not self.gstin.startswith(self.state_code):
            raise ValueError("GSTIN and supplier state must agree")
        return self
