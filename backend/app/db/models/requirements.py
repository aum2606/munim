from typing import Any

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRecord


class RequirementSchema(TenantRecord):
    __tablename__ = "requirement_schemas"
    __table_args__ = (
        UniqueConstraint("tenant_id", "category"),
        Index("ix_requirements_tenant_category", "tenant_id", "category"),
    )
    category: Mapped[str]
    json_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    defaults: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    question_templates: Mapped[dict[str, str]] = mapped_column(JSONB)
