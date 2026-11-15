import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.context import Role


class StrictRequest(BaseModel):
    """Request bodies reject unknown fields (no mass assignment)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Password = Annotated[str, Field(min_length=10, max_length=128)]  # max stops Argon2 DoS


class _EmailMixin(StrictRequest):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _lowercase(cls, value: str) -> str:
        return value.lower()


class RegisterRequest(_EmailMixin):
    business_name: str = Field(min_length=1, max_length=120)
    business_type: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    password: Password


class LoginRequest(_EmailMixin):
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (a label, not a secret)
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: Role
    is_active: bool


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    business_type: str
    timezone: str


class MeResponse(BaseModel):
    user: UserOut
    tenant: TenantOut


class UserCreate(_EmailMixin):
    name: str = Field(min_length=1, max_length=120)
    password: Password
    role: Role = Role.STAFF


class UserUpdate(StrictRequest):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
