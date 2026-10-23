from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRecord


class QuoteStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending_approval"
    SENT = "sent"
    VIEWED = "viewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Quote(TenantRecord):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "quote_number"),
        UniqueConstraint("tenant_id", "source_message_id"),
        Index("ix_quotes_tenant_status", "tenant_id", "status"),
        CheckConstraint(
            "total_paise >= 0 AND subtotal_paise >= 0 AND discount_paise >= 0",
            name="quote_money_nonnegative",
        ),
        ForeignKeyConstraint(["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_message_id"], ["messages.tenant_id", "messages.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "approved_by"], ["users.tenant_id", "users.id"]),
    )
    lead_id: Mapped[UUID]
    conversation_id: Mapped[UUID]
    source_message_id: Mapped[UUID]
    quote_number: Mapped[str]
    status: Mapped[QuoteStatus] = mapped_column(
        Enum(
            QuoteStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="quote_status",
        ),
        default=QuoteStatus.PENDING,
    )
    version: Mapped[int] = mapped_column(default=1)
    seller: Mapped[dict[str, Any]] = mapped_column(JSONB)
    customer_label: Mapped[str]
    customer_state: Mapped[str | None]
    terms: Mapped[str]
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subtotal_paise: Mapped[int] = mapped_column(BigInteger)
    discount_paise: Mapped[int] = mapped_column(BigInteger)
    cgst_paise: Mapped[int] = mapped_column(BigInteger)
    sgst_paise: Mapped[int] = mapped_column(BigInteger)
    igst_paise: Mapped[int] = mapped_column(BigInteger)
    round_off_paise: Mapped[int] = mapped_column(BigInteger)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    pricing_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    pdf_path: Mapped[str | None]
    approved_by: Mapped[UUID | None]
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuoteItem(TenantRecord):
    __tablename__ = "quote_items"
    __table_args__ = (
        Index("ix_quote_items_tenant_quote", "tenant_id", "quote_id"),
        CheckConstraint(
            "qty > 0 AND unit_price_paise >= 0 AND line_total_paise >= 0",
            name="quote_line_positive",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"], ["quotes.tenant_id", "quotes.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "catalog_item_id"], ["catalog_items.tenant_id", "catalog_items.id"]
        ),
    )
    quote_id: Mapped[UUID]
    position: Mapped[int]
    catalog_item_id: Mapped[UUID | None]
    sku: Mapped[str | None]
    description: Mapped[str]
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit: Mapped[str]
    unit_price_paise: Mapped[int] = mapped_column(BigInteger)
    addon_paise: Mapped[int] = mapped_column(BigInteger)
    discount_paise: Mapped[int] = mapped_column(BigInteger)
    gst_rate: Mapped[int]
    hsn_sac: Mapped[str]
    line_total_paise: Mapped[int] = mapped_column(BigInteger)
    options: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    needs_owner_pricing: Mapped[bool] = mapped_column(default=False)


class QuoteSequence(TenantRecord):
    __tablename__ = "quote_sequences"
    __table_args__ = (
        UniqueConstraint("tenant_id", "financial_year"),
        Index("ix_quote_sequences_tenant_year", "tenant_id", "financial_year"),
    )
    financial_year: Mapped[str]
    last_value: Mapped[int]
