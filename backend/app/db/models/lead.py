from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Enum, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
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
