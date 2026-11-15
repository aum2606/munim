import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import EMBEDDING_DIM, Base, IdentityMixin, TenantMixin, enum_type

# 'simple' = no stemming or stop words, which suits Hindi, Gujarati and romanised Hinglish.
_TSV = "to_tsvector('simple', {col})"


class DocumentSource(enum.StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    FAQ = "faq"


class DocumentStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class StockStatus(enum.StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    ON_ORDER = "on_order"
    NA = "na"


class GapStatus(enum.StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    IGNORED = "ignored"


class ImportStatus(enum.StrEnum):
    PREVIEWED = "previewed"
    COMMITTED = "committed"


class Document(IdentityMixin, TenantMixin, Base):
    """An uploaded file, or one FAQ (a single Q/A chunk)."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_tenant_id_source_type", "tenant_id", "source_type"),)

    title: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[DocumentSource] = mapped_column(enum_type(DocumentSource))
    storage_path: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus), default=DocumentStatus.PENDING
    )
    error: Mapped[str | None] = mapped_column(Text)


class Chunk(IdentityMixin, TenantMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_tenant_id_document_id", "tenant_id", "document_id"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed(_TSV.format(col="content"), persisted=True))
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class CatalogItem(IdentityMixin, TenantMixin, Base):
    """Structured price list row. Prices come from here and only here (BUILD_PLAN.md section 2)."""

    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku"),
        CheckConstraint("base_price_paise >= 0", name="price_non_negative"),
        CheckConstraint("gst_rate IN (0, 5, 12, 18, 28)", name="gst_rate_valid"),
        Index("ix_catalog_items_tenant_id_category", "tenant_id", "category"),
        Index("ix_catalog_items_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_catalog_items_search_text_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        Index(
            "ix_catalog_items_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'")
    )  # stored lowercase
    category: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(24), default="unit", server_default="unit")
    base_price_paise: Mapped[int] = mapped_column(BigInteger)
    gst_rate: Mapped[int] = mapped_column(Integer, default=18, server_default="18")
    hsn_sac: Mapped[str | None] = mapped_column(String(16))
    stock_status: Mapped[StockStatus] = mapped_column(
        enum_type(StockStatus), default=StockStatus.NA
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # name + aliases + category + description, maintained by the app (array_to_string is not
    # immutable, so it cannot live in a generated column). Feeds the embedding, tsv and trigrams.
    search_text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed(_TSV.format(col="search_text"), persisted=True)
    )


class KnowledgeGap(IdentityMixin, TenantMixin, Base):
    """A question the bot could not answer from the knowledge base."""

    __tablename__ = "knowledge_gaps"
    __table_args__ = (UniqueConstraint("tenant_id", "question_key"),)

    question: Mapped[str] = mapped_column(Text)
    question_key: Mapped[str] = mapped_column(String(200))  # normalised, to count repeats
    example_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    occurrences: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[GapStatus] = mapped_column(enum_type(GapStatus), default=GapStatus.OPEN)
    answer_text: Mapped[str | None] = mapped_column(Text)
    converted_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )


class ImportJob(IdentityMixin, TenantMixin, Base):
    """A catalogue file awaiting review: column mapping is confirmed before anything is saved."""

    __tablename__ = "import_jobs"
    __table_args__ = (Index("ix_import_jobs_tenant_id_created_at", "tenant_id", "created_at"),)

    filename: Mapped[str] = mapped_column(String(200))  # display only; never used as a path
    storage_path: Mapped[str] = mapped_column(String(300))
    headers: Mapped[list[str]] = mapped_column(JSONB)
    mapping: Mapped[dict[str, str]] = mapped_column(JSONB)  # field -> source column header
    row_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[ImportStatus] = mapped_column(
        enum_type(ImportStatus), default=ImportStatus.PREVIEWED
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
