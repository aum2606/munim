from typing import Any

from sqlalchemy import CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRecord


class PrivacyErasure(TenantRecord):
    __tablename__ = "privacy_erasures"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_fingerprint"),
        Index("ix_privacy_tenant_status", "tenant_id", "status"),
        CheckConstraint("status IN ('pending_files','complete')", name="privacy_erasure_status"),
    )
    customer_fingerprint: Mapped[str] = mapped_column(String(64))
    channel_fingerprints: Mapped[list[str]] = mapped_column(JSONB, default=list)
    files: Mapped[list[str]] = mapped_column(JSONB, default=list)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(default="pending_files")
