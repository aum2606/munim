import enum
import uuid
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdentityMixin, TenantMixin, enum_type


class AgentRunStatus(enum.StrEnum):
    OK = "ok"
    ERROR = "error"


class AgentRun(IdentityMixin, TenantMixin, Base):
    """One row per LLM-backed agent call. Input/output may hold customer text: it is deleted
    with the customer (Phase 5) and never logged."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_agent_runs_tenant_id_message_id", "tenant_id", "message_id"),
    )

    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )  # the inbound message that triggered the run
    agent: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(80))  # "<template>@<sha12>"
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate_micros: Mapped[int] = mapped_column(BigInteger, default=0)  # at list price
    status: Mapped[AgentRunStatus] = mapped_column(enum_type(AgentRunStatus))
    error: Mapped[str | None] = mapped_column(Text)
