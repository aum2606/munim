import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Fixed by the pgvector column type. A model with a different output size needs a migration.
EMBEDDING_DIM = 384

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdentityMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantMixin:
    """Every table except `tenants` carries a non-null tenant_id."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))


def enum_type(enum_cls: type[enum.Enum]) -> sa.Enum:
    """Enum stored as a short string with a CHECK constraint (no native PG enum to migrate)."""
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=24,
        create_constraint=True,
        validate_strings=True,
        name=enum_cls.__name__.lower(),
        values_callable=lambda e: [m.value for m in e],
    )
