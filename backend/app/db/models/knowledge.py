from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRecord

EMBEDDING_DIMENSION = 1024


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SourceType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    FAQ = "faq_form"


class Document(TenantRecord):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        Index("ix_documents_tenant_status", "tenant_id", "status"),
    )
    title: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[SourceType] = mapped_column(
        Enum(
            SourceType,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="source_type",
        )
    )
    storage_path: Mapped[str]
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="document_status",
        ),
        default=DocumentStatus.PENDING,
    )
    error: Mapped[str | None]


class Chunk(TenantRecord):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        Index("ix_chunks_tenant_document", "tenant_id", "document_id"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    document_id: Mapped[UUID]
    content: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_DIMENSION))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True)
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    token_count: Mapped[int] = mapped_column(Integer)


class StockStatus(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    ON_ORDER = "on_order"
    NA = "na"


class CatalogItem(TenantRecord):
    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("base_price_paise >= 0", name="catalog_price_nonnegative"),
        CheckConstraint("gst_rate IN (0,5,12,18,28)", name="catalog_gst_rate"),
        Index("ix_catalog_tenant_active", "tenant_id", "is_active"),
        Index("ix_catalog_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_catalog_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_catalog_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    sku: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    category: Mapped[str] = mapped_column(String(100), default="general")
    description: Mapped[str] = mapped_column(default="")
    unit: Mapped[str] = mapped_column(default="piece")
    base_price_paise: Mapped[int] = mapped_column(BigInteger)
    gst_rate: Mapped[int] = mapped_column(Integer, default=18)
    hsn_sac: Mapped[str] = mapped_column(default="")
    stock_status: Mapped[StockStatus] = mapped_column(
        Enum(
            StockStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="stock_status",
        ),
        default=StockStatus.NA,
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_DIMENSION))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', name || ' ' || description || ' ' || category)", persisted=True
        ),
    )


class RuleType(StrEnum):
    QTY_TIER = "qty_tier"
    ADDON = "addon"
    MIN_ORDER = "min_order"
    SEASONAL = "seasonal"


class PricingRule(TenantRecord):
    __tablename__ = "pricing_rules"
    __table_args__ = (
        Index("ix_rules_tenant_catalog", "tenant_id", "catalog_item_id"),
        ForeignKeyConstraint(
            ["tenant_id", "catalog_item_id"], ["catalog_items.tenant_id", "catalog_items.id"]
        ),
    )
    catalog_item_id: Mapped[UUID | None]
    category: Mapped[str | None]
    rule_type: Mapped[RuleType] = mapped_column(
        Enum(
            RuleType,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [v.value for v in e],
            name="rule_type",
        )
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    priority: Mapped[int] = mapped_column(default=0)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CatalogImport(TenantRecord):
    __tablename__ = "catalog_imports"
    __table_args__ = (Index("ix_imports_tenant_id", "tenant_id", "id"),)
    headers: Mapped[list[str]] = mapped_column(JSONB)
    rows: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    mapping: Mapped[dict[str, str]] = mapped_column(JSONB)
    committed: Mapped[bool] = mapped_column(default=False)
