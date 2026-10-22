from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRecord


class ConversationMode(StrEnum):
    AI = "ai"
    ASSIST = "assist"
    HUMAN = "human"


class ConversationStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Customer(TenantRecord):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        Index("ix_customers_tenant_id", "tenant_id", "id"),
    )
    name: Mapped[str | None]
    phone: Mapped[str | None]
    email: Mapped[str | None]
    channel_identities: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    language_pref: Mapped[str] = mapped_column(default="en")
    city: Mapped[str | None]
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    notes: Mapped[str] = mapped_column(default="")


class Conversation(TenantRecord):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        Index("ix_conversations_tenant_status", "tenant_id", "status"),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]),
    )
    customer_id: Mapped[UUID]
    channel: Mapped[str] = mapped_column(default="web")
    mode: Mapped[ConversationMode] = mapped_column(
        Enum(
            ConversationMode,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="conversation_mode",
        ),
        default=ConversationMode.AI,
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(
            ConversationStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="conversation_status",
        ),
        default=ConversationStatus.OPEN,
    )
    last_customer_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_business_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_flow: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Direction(StrEnum):
    IN = "in"
    OUT = "out"


class SenderType(StrEnum):
    CUSTOMER = "customer"
    AI = "ai"
    STAFF = "staff"
    SYSTEM = "system"


class Message(TenantRecord):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "conversation_id", "external_id"),
        UniqueConstraint("tenant_id", "in_reply_to_id"),
        Index("ix_messages_tenant_conversation", "tenant_id", "conversation_id", "created_at"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "in_reply_to_id"], ["messages.tenant_id", "messages.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name="fk_message_agent_run",
            use_alter=True,
        ),
    )
    conversation_id: Mapped[UUID]
    direction: Mapped[Direction] = mapped_column(
        Enum(
            Direction,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="message_direction",
        )
    )
    sender_type: Mapped[SenderType] = mapped_column(
        Enum(
            SenderType,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="sender_type",
        )
    )
    content: Mapped[str]
    content_type: Mapped[str] = mapped_column(default="text")
    external_id: Mapped[str | None]
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    language: Mapped[str | None]
    intent: Mapped[str | None]
    agent_run_id: Mapped[UUID | None]
    in_reply_to_id: Mapped[UUID | None]
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WidgetSession(TenantRecord):
    __tablename__ = "widget_sessions"
    __table_args__ = (
        Index("ix_widget_sessions_tenant_id", "tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
    )
    conversation_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GapStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    IGNORED = "ignored"


class KnowledgeGap(TenantRecord):
    __tablename__ = "knowledge_gaps"
    __table_args__ = (
        Index("ix_gaps_tenant_status", "tenant_id", "status"),
        UniqueConstraint("tenant_id", "question"),
        ForeignKeyConstraint(
            ["tenant_id", "example_message_id"], ["messages.tenant_id", "messages.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "converted_document_id"], ["documents.tenant_id", "documents.id"]
        ),
    )
    question: Mapped[str]
    example_message_id: Mapped[UUID | None]
    occurrences: Mapped[int] = mapped_column(default=1)
    status: Mapped[GapStatus] = mapped_column(
        Enum(
            GapStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="gap_status",
        ),
        default=GapStatus.OPEN,
    )
    answer_text: Mapped[str | None]
    converted_document_id: Mapped[UUID | None]
