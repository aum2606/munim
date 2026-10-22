from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models import Role


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_name: str = Field(min_length=1, max_length=200)
    business_type: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshInput(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    email: EmailStr
    name: str
    role: Role


class RenameInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
