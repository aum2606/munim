import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdentityMixin, TenantMixin, enum_type
from app.db.models.chat import Channel


class RuleType(enum.StrEnum):
    QTY_TIER = "qty_tier"
    ADDON = "addon"
    MIN_ORDER = "min_order"


class LeadStage(enum.StrEnum):
    NEW = "new"
    ENGAGED = "engaged"
    QUALIFIED = "qualified"
    QUOTED = "quoted"
    NEGOTIATING = "negotiating"
    WON = "won"
    LOST = "lost"
    DORMANT = "dormant"


class QuoteStatus(enum.StrEnum):
    PENDING_APPROVAL = "pending_approval"
    SENT = "sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RequirementSchema(IdentityMixin, TenantMixin, Base):
    """What to ask a customer before quoting, per kind of work (BUILD_PLAN.md section 5.3)."""

    __tablename__ = "requirement_schemas"
    __table_args__ = (UniqueConstraint("tenant_id", "category"),)

    category: Mapped[str] = mapped_column(String(60))
    json_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)  # properties + required
    defaults: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )  # used when the customer says "don't know"
    question_hints: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )  # slot -> how to ask for it


class PricingRule(IdentityMixin, TenantMixin, Base):
    """A quantity tier, add-on or minimum order for one item or a whole category."""

    __tablename__ = "pricing_rules"
    __table_args__ = (
        CheckConstraint("catalog_item_id IS NOT NULL OR category IS NOT NULL", name="has_a_target"),
        Index("ix_pricing_rules_tenant_id_catalog_item_id", "tenant_id", "catalog_item_id"),
        Index("ix_pricing_rules_tenant_id_category", "tenant_id", "category"),
    )

    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE")
    )
    category: Mapped[str | None] = mapped_column(String(80))
    rule_type: Mapped[RuleType] = mapped_column(enum_type(RuleType))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Lead(IdentityMixin, TenantMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_id"),
        Index("ix_leads_tenant_id_stage", "tenant_id", "stage"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    stage: Mapped[LeadStage] = mapped_column(enum_type(LeadStage), default=LeadStage.NEW)
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    summary: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    category: Mapped[str | None] = mapped_column(String(60))
    estimated_value_paise: Mapped[int | None] = mapped_column(BigInteger)
    source_channel: Mapped[Channel] = mapped_column(enum_type(Channel))


class LeadEvent(IdentityMixin, TenantMixin, Base):
    __tablename__ = "lead_events"
    __table_args__ = (Index("ix_lead_events_tenant_id_lead_id", "tenant_id", "lead_id"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(40))
    from_value: Mapped[str | None] = mapped_column(String(60))
    to_value: Mapped[str | None] = mapped_column(String(60))
    actor: Mapped[str] = mapped_column(String(40))  # "ai", or the user's id
    note: Mapped[str | None] = mapped_column(Text)


class Quote(IdentityMixin, TenantMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "quote_number"),
        Index("ix_quotes_tenant_id_status", "tenant_id", "status"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    quote_number: Mapped[str] = mapped_column(String(32))
    status: Mapped[QuoteStatus] = mapped_column(
        enum_type(QuoteStatus), default=QuoteStatus.PENDING_APPROVAL
    )
    subtotal_paise: Mapped[int] = mapped_column(BigInteger)  # before discounts
    discount_paise: Mapped[int] = mapped_column(BigInteger)
    cgst_paise: Mapped[int] = mapped_column(BigInteger)
    sgst_paise: Mapped[int] = mapped_column(BigInteger)
    igst_paise: Mapped[int] = mapped_column(BigInteger)
    round_off_paise: Mapped[int] = mapped_column(BigInteger)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    valid_until: Mapped[date] = mapped_column(Date)
    buyer_state_code: Mapped[str | None] = mapped_column(String(2))
    pdf_path: Mapped[str | None] = mapped_column(String(300))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuoteItem(IdentityMixin, TenantMixin, Base):
    __tablename__ = "quote_items"
    __table_args__ = (Index("ix_quote_items_tenant_id_quote_id", "tenant_id", "quote_id"),)

    quote_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(String(300))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(24))
    unit_price_paise: Mapped[int] = mapped_column(BigInteger)
    discount_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    gst_rate: Mapped[int] = mapped_column(Integer)
    hsn_sac: Mapped[str | None] = mapped_column(String(16))
    line_total_paise: Mapped[int] = mapped_column(BigInteger)  # before tax, after discount
    needs_owner_pricing: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


class QuoteSequence(IdentityMixin, TenantMixin, Base):
    """Last quote number issued per tenant per financial year."""

    __tablename__ = "quote_sequences"
    __table_args__ = (UniqueConstraint("tenant_id", "fiscal_year"),)

    fiscal_year: Mapped[str] = mapped_column(String(7))
    last_number: Mapped[int] = mapped_column(Integer, default=0)
