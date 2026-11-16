from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdentityMixin, TenantMixin, enum_type
from app.db.models.chat import Channel


class ChannelAccount(IdentityMixin, TenantMixin, Base):
    """A business's WhatsApp number. `external_id` is Meta's phone_number_id: the key an incoming
    webhook is routed by, so it is unique across all tenants."""

    __tablename__ = "channel_accounts"
    __table_args__ = (
        UniqueConstraint("channel", "external_id"),
        UniqueConstraint("tenant_id", "channel"),  # one number per business, for now
    )

    channel: Mapped[Channel] = mapped_column(enum_type(Channel))
    external_id: Mapped[str] = mapped_column(String(64))
    display_phone: Mapped[str | None] = mapped_column(String(24))
    credentials_encrypted: Mapped[str] = mapped_column(Text)  # Fernet token, see core/crypto.py
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
