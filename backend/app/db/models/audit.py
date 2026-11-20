import enum
import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdentityMixin, TenantMixin


class AuditAction(enum.StrEnum):
    WHATSAPP_CONNECTED = "whatsapp_connected"
    WHATSAPP_DISCONNECTED = "whatsapp_disconnected"
    CUSTOMER_ERASED = "customer_erased"
    QUOTE_EDITED = "quote_edited"
    QUOTE_APPROVED = "quote_approved"
    QUOTE_REJECTED = "quote_rejected"
    USER_CREATED = "user_created"
    USER_DEACTIVATED = "user_deactivated"
    USER_REACTIVATED = "user_reactivated"


class AuditEvent(IdentityMixin, TenantMixin, Base):
    """Who did a sensitive thing, and to what. Rows are only ever added.

    `target` is a reference (a quote number, an id), never customer text: erasing a customer must
    not leave their words behind here.
    """

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_tenant_id_created_at", "tenant_id", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40))
    target: Mapped[str | None] = mapped_column(String(80))
