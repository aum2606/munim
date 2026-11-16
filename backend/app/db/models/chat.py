import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdentityMixin, TenantMixin, enum_type


class Channel(enum.StrEnum):
    PLAYGROUND = "playground"
    WHATSAPP = "whatsapp"


class ConversationMode(enum.StrEnum):
    AI = "ai"
    HUMAN = "human"


class ConversationStatus(enum.StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Direction(enum.StrEnum):
    IN = "in"
    OUT = "out"


class SenderType(enum.StrEnum):
    CUSTOMER = "customer"
    AI = "ai"
    STAFF = "staff"
    SYSTEM = "system"


class Customer(IdentityMixin, TenantMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index(
            "uq_customers_tenant_id_phone",
            "tenant_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
    )

    name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))  # E.164
    language_pref: Mapped[str | None] = mapped_column(String(12))


class Conversation(IdentityMixin, TenantMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_tenant_id_mode", "tenant_id", "mode"),)

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    channel: Mapped[Channel] = mapped_column(enum_type(Channel))
    mode: Mapped[ConversationMode] = mapped_column(
        enum_type(ConversationMode), default=ConversationMode.AI
    )
    status: Mapped[ConversationStatus] = mapped_column(
        enum_type(ConversationStatus), default=ConversationStatus.OPEN
    )
    last_customer_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_business_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_flow: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class Message(IdentityMixin, TenantMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index(
            "ix_messages_tenant_id_conversation_id_created_at",
            "tenant_id",
            "conversation_id",
            "created_at",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    direction: Mapped[Direction] = mapped_column(enum_type(Direction))
    sender_type: Mapped[SenderType] = mapped_column(enum_type(SenderType))
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(12))
    intent: Mapped[str | None] = mapped_column(String(24))
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    # Set on the message that delivers a quotation to the customer.
    quote_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quotes.id", ondelete="SET NULL"))
    # Set once an inbound message has been answered (or deliberately skipped).
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
