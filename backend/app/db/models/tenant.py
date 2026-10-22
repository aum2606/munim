import secrets
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdentityMixin, TenantMixin


class Tenant(IdentityMixin, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(200))
    business_type: Mapped[str] = mapped_column(String(100))
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str | None] = mapped_column(String(2))
    address: Mapped[str | None]
    phone: Mapped[str | None] = mapped_column(String(20))
    logo_url: Mapped[str | None]
    timezone: Mapped[str] = mapped_column(default="Asia/Kolkata")
    plan: Mapped[str] = mapped_column(default="pilot")
    widget_public_key: Mapped[str] = mapped_column(
        unique=True, default=lambda: secrets.token_urlsafe(32)
    )


class TenantSettings(TenantMixin, Base):
    __tablename__ = "tenant_settings"
    __table_args__ = (UniqueConstraint("tenant_id"),)
    tone: Mapped[str] = mapped_column(default="friendly")
    languages: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: ["en"])
    business_hours: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    auto_send_quotes: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_send_limit_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    max_auto_discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    quote_validity_days: Mapped[int] = mapped_column(Integer, default=7)
    followup_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    handoff_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    owner_notify_whatsapp: Mapped[bool] = mapped_column(default=False)
