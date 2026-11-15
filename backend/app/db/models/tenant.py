from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdentityMixin, TenantMixin


class Tenant(IdentityMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120))
    business_type: Mapped[str] = mapped_column(String(60))
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Kolkata", server_default="Asia/Kolkata"
    )


class TenantSettings(IdentityMixin, TenantMixin, Base):
    __tablename__ = "tenant_settings"
    __table_args__ = (UniqueConstraint("tenant_id"),)  # one row per tenant; also the lookup index

    tone: Mapped[str] = mapped_column(String(24), default="friendly", server_default="friendly")
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(8)), default=lambda: ["en", "hi"], server_default=text("'{en,hi}'")
    )
    business_hours: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    # Percent, not money. Decimal because it feeds pricing decisions later.
    max_auto_discount_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0"), server_default="0"
    )
    quote_validity_days: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
