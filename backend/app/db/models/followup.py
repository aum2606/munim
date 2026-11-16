import enum
import uuid

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdentityMixin, TenantMixin, enum_type


class FollowUpStatus(enum.StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    DISMISSED = "dismissed"


class FollowUp(IdentityMixin, TenantMixin, Base):
    """A suggested nudge for a quote the customer has not answered. The owner decides."""

    __tablename__ = "follow_ups"
    __table_args__ = (Index("ix_follow_ups_tenant_id_status", "tenant_id", "status"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    quote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quotes.id", ondelete="CASCADE"),
        unique=True,  # one nudge per quote
    )
    draft: Mapped[str] = mapped_column(Text)
    status: Mapped[FollowUpStatus] = mapped_column(
        enum_type(FollowUpStatus), default=FollowUpStatus.DRAFT
    )
