from datetime import datetime
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
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRecord


class LeadStage(StrEnum):
    NEW = "new"
    ENGAGED = "engaged"
    QUALIFIED = "qualified"
    QUOTED = "quoted"
    NEGOTIATING = "negotiating"
    WON = "won"
    LOST = "lost"
    DORMANT = "dormant"


class Lead(TenantRecord):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "conversation_id"),
        Index("ix_leads_tenant_stage", "tenant_id", "stage"),
        CheckConstraint("score >= 0 AND score <= 100", name="lead_score_bounds"),
        CheckConstraint("estimated_value_paise >= 0", name="lead_value_nonnegative"),
        ForeignKeyConstraint(["tenant_id", "assigned_to"], ["users.tenant_id", "users.id"]),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
    )
    customer_id: Mapped[UUID]
    conversation_id: Mapped[UUID]
    stage: Mapped[LeadStage] = mapped_column(
        Enum(
            LeadStage,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="lead_stage",
        ),
        default=LeadStage.NEW,
    )
    category: Mapped[str]
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    summary: Mapped[str] = mapped_column(default="")
    source_channel: Mapped[str] = mapped_column(default="web")
    score: Mapped[int] = mapped_column(default=0, server_default="0")
    estimated_value_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    assigned_to: Mapped[UUID | None]
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_reason: Mapped[str | None]
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default="{}")
    stage_override: Mapped[bool] = mapped_column(default=False, server_default="false")
    last_scored_message_id: Mapped[UUID | None]


class LeadEvent(TenantRecord):
    __tablename__ = "lead_events"
    __table_args__ = (
        Index("ix_lead_events_tenant_lead", "tenant_id", "lead_id", "created_at"),
        ForeignKeyConstraint(["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"]),
    )
    lead_id: Mapped[UUID]
    event_type: Mapped[str]
    from_value: Mapped[str | None]
    to_value: Mapped[str | None]
    actor: Mapped[str]
    note: Mapped[str] = mapped_column(default="")


class Followup(TenantRecord):
    __tablename__ = "followups"
    __table_args__ = (
        Index("ix_followups_tenant_status", "tenant_id", "status", "scheduled_at"),
        UniqueConstraint("tenant_id", "lead_id", "kind", "source_at"),
        CheckConstraint(
            "status IN ('scheduled','sent','cancelled','skipped')", name="followup_status"
        ),
        CheckConstraint("kind IN ('no_reply','quote_reminder','reengage')", name="followup_kind"),
        ForeignKeyConstraint(["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"]),
    )
    lead_id: Mapped[UUID]
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(default="scheduled")
    kind: Mapped[str]
    draft_text: Mapped[str]
    requires_template: Mapped[bool] = mapped_column(default=False)


class Handoff(TenantRecord):
    __tablename__ = "handoffs"
    __table_args__ = (
        Index("ix_handoffs_tenant_status", "tenant_id", "status"),
        Index(
            "ix_handoffs_one_open",
            "tenant_id",
            "conversation_id",
            unique=True,
            postgresql_where="status = 'open'",
        ),
        CheckConstraint("status IN ('open','resolved')", name="handoff_status"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "resolved_by"], ["users.tenant_id", "users.id"]),
    )
    conversation_id: Mapped[UUID]
    reason: Mapped[str]
    summary: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    resolved_by: Mapped[UUID | None]


class ReplyDraft(TenantRecord):
    __tablename__ = "reply_drafts"
    __table_args__ = (
        Index("ix_reply_drafts_tenant_conversation", "tenant_id", "conversation_id"),
        UniqueConstraint("tenant_id", "source_message_id"),
        CheckConstraint("status IN ('pending','sent','discarded')", name="reply_draft_status"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_message_id"], ["messages.tenant_id", "messages.id"]
        ),
    )
    conversation_id: Mapped[UUID]
    source_message_id: Mapped[UUID]
    content: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
