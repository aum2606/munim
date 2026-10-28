from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRecord


class AnalyticsEventType(StrEnum):
    MESSAGE_IN = "message_in"
    AI_REPLY = "ai_reply"
    STAFF_REPLY = "staff_reply"
    HANDOFF = "handoff"
    QUOTE_GENERATED = "quote_generated"
    QUOTE_SENT = "quote_sent"
    QUOTE_ACCEPTED = "quote_accepted"
    QUOTE_REJECTED = "quote_rejected"
    LEAD_WON = "lead_won"
    LEAD_LOST = "lead_lost"
    CATALOG_ENQUIRY = "catalog_enquiry"
    FOLLOWUP_SENT = "followup_sent"
    INSIGHT_ASKED = "insight_asked"
    DIGEST_OPENED = "digest_opened"


class AnalyticsEvent(TenantRecord):
    __tablename__ = "analytics_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event", "source_key"),
        Index("ix_analytics_tenant_event_time", "tenant_id", "event", "occurred_at"),
    )
    event: Mapped[AnalyticsEventType] = mapped_column(
        Enum(
            AnalyticsEventType,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="analytics_event_type",
        )
    )
    source_key: Mapped[str] = mapped_column(String(200))
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WeeklyDigest(TenantRecord):
    __tablename__ = "weekly_digests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "week_start"),
        Index("ix_digests_tenant_week", "tenant_id", "week_start"),
    )
    week_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB)
