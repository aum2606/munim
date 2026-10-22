from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin


class Role(StrEnum):
    OWNER = "owner"
    STAFF = "staff"
    ADMIN = "admin"


class User(TenantMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_tenant_id_id", "tenant_id", "id"),
        UniqueConstraint("tenant_id", "id"),
    )
    email: Mapped[str] = mapped_column(String(254), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str]
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(
        Enum(Role, values_callable=lambda e: [v.value for v in e], name="user_role"),
        default=Role.STAFF,
    )
    is_active: Mapped[bool] = mapped_column(default=True)


class RefreshSession(TenantMixin, Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (
        Index("ix_refresh_sessions_tenant_id_id", "tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"]),
    )
    user_id: Mapped[UUID] = mapped_column()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False)
