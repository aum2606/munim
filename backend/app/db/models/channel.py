from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRecord


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    RETRY = "retry"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    BLOCKED = "blocked"


def status_type[T: StrEnum](enum: type[T], name: str) -> Enum:
    return Enum(
        enum,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda values: [value.value for value in values],
        name=name,
    )


class ChannelAccount(TenantRecord):
    __tablename__ = "channel_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("type", "external_id"),
        Index("ix_channel_accounts_tenant_type", "tenant_id", "type"),
    )
    type: Mapped[str] = mapped_column(default="whatsapp")
    external_id: Mapped[str]
    business_account_id: Mapped[str]
    credentials_encrypted: Mapped[str]
    status: Mapped[AccountStatus] = mapped_column(
        status_type(AccountStatus, "channel_account_status"), default=AccountStatus.ACTIVE
    )


class WhatsAppContact(TenantRecord):
    __tablename__ = "whatsapp_contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "account_id", "wa_id"),
        UniqueConstraint("tenant_id", "conversation_id"),
        Index("ix_wa_contacts_tenant_customer", "tenant_id", "customer_id"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["channel_accounts.tenant_id", "channel_accounts.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "consent_by"], ["users.tenant_id", "users.id"]),
    )
    account_id: Mapped[UUID]
    wa_id: Mapped[str]
    customer_id: Mapped[UUID]
    conversation_id: Mapped[UUID]
    opted_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opted_out: Mapped[bool] = mapped_column(default=False, server_default="false")
    consent_note: Mapped[str] = mapped_column(default="")
    consent_by: Mapped[UUID | None]


class WhatsAppTemplate(TenantRecord):
    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "account_id", "name", "language"),
        Index("ix_wa_templates_tenant_account", "tenant_id", "account_id"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["channel_accounts.tenant_id", "channel_accounts.id"]
        ),
    )
    account_id: Mapped[UUID]
    name: Mapped[str]
    language: Mapped[str]
    provider_id: Mapped[str]
    status: Mapped[str]
    body_text: Mapped[str]
    usable: Mapped[bool] = mapped_column(default=False)


class ChannelDelivery(TenantRecord):
    __tablename__ = "channel_deliveries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id"),
        UniqueConstraint("tenant_id", "account_id", "provider_message_id"),
        Index("ix_deliveries_tenant_due", "tenant_id", "status", "next_attempt_at"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["channel_accounts.tenant_id", "channel_accounts.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "message_id"], ["messages.tenant_id", "messages.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "template_id"], ["whatsapp_templates.tenant_id", "whatsapp_templates.id"]
        ),
    )
    account_id: Mapped[UUID]
    message_id: Mapped[UUID]
    template_id: Mapped[UUID | None]
    status: Mapped[DeliveryStatus] = mapped_column(
        status_type(DeliveryStatus, "channel_delivery_status"), default=DeliveryStatus.QUEUED
    )
    provider_message_id: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None]


class ChannelStatusReceipt(TenantRecord):
    __tablename__ = "channel_status_receipts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "account_id", "provider_message_id", "status"),
        Index(
            "ix_channel_status_tenant_provider", "tenant_id", "account_id", "provider_message_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["channel_accounts.tenant_id", "channel_accounts.id"]
        ),
    )
    account_id: Mapped[UUID]
    provider_message_id: Mapped[str]
    status: Mapped[str]
