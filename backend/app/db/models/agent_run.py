from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AgentRunStatus
from app.db.base import Base, TenantMixin


class AgentRun(TenantMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_agent_runs_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["messages.tenant_id", "messages.id"],
            name="fk_run_message",
            use_alter=True,
        ),
        Index("ix_agent_runs_tenant_id_message_id", "tenant_id", "message_id"),
        CheckConstraint("status IN ('success', 'error', 'invalid')", name="agent_run_status"),
    )
    message_id: Mapped[UUID | None]
    agent: Mapped[str]
    model: Mapped[str]
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    latency_ms: Mapped[int]
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(
            AgentRunStatus,
            native_enum=False,
            length=None,
            values_callable=lambda statuses: [status.value for status in statuses],
        )
    )
    error: Mapped[str | None]
