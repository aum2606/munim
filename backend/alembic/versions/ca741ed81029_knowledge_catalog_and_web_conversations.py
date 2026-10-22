"""knowledge catalog and web conversations"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "ca741ed81029"
down_revision = "aa73c6cdbab4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_imports",
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("committed", sa.Boolean(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_imports_tenant_id", "catalog_imports", ["tenant_id", "id"], unique=False)
    op.create_table(
        "catalog_items",
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("base_price_paise", sa.BigInteger(), nullable=False),
        sa.Column("gst_rate", sa.Integer(), nullable=False),
        sa.Column("hsn_sac", sa.String(), nullable=False),
        sa.Column(
            "stock_status",
            sa.Enum(
                "in_stock",
                "out_of_stock",
                "on_order",
                "na",
                name="stock_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', name || ' ' || description || ' ' || category)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("base_price_paise >= 0", name="catalog_price_nonnegative"),
        sa.CheckConstraint("gst_rate IN (0,5,12,18,28)", name="catalog_gst_rate"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "sku"),
    )
    op.create_index(
        "ix_catalog_embedding",
        "catalog_items",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_catalog_name_trgm",
        "catalog_items",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_catalog_tenant_active", "catalog_items", ["tenant_id", "is_active"], unique=False
    )
    op.create_index(
        "ix_catalog_tsv", "catalog_items", ["tsv"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "customers",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("channel_identities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("language_pref", sa.String(), nullable=False),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("notes", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id", "id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(
                "pdf",
                "docx",
                "txt",
                "faq_form",
                name="source_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "failed",
                name="document_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index(
        "ix_documents_tenant_status", "documents", ["tenant_id", "status"], unique=False
    )
    op.create_table(
        "chunks",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', content)", persisted=True),
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index(
        "ix_chunks_embedding",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_chunks_tenant_document", "chunks", ["tenant_id", "document_id"], unique=False
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], unique=False, postgresql_using="gin")
    op.create_table(
        "conversations",
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column(
            "mode",
            sa.Enum(
                "ai",
                "assist",
                "human",
                name="conversation_mode",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "closed",
                name="conversation_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("last_customer_msg_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_business_msg_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_flow", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index(
        "ix_conversations_tenant_status", "conversations", ["tenant_id", "status"], unique=False
    )
    op.create_table(
        "pricing_rules",
        sa.Column("catalog_item_id", sa.Uuid(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column(
            "rule_type",
            sa.Enum(
                "qty_tier",
                "addon",
                "min_order",
                "seasonal",
                name="rule_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "catalog_item_id"],
            ["catalog_items.tenant_id", "catalog_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rules_tenant_catalog", "pricing_rules", ["tenant_id", "catalog_item_id"], unique=False
    )
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum(
                "in", "out", name="message_direction", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column(
            "sender_type",
            sa.Enum(
                "customer",
                "ai",
                "staff",
                "system",
                name="sender_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("intent", sa.String(), nullable=True),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("in_reply_to_id", sa.Uuid(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "in_reply_to_id"],
            ["messages.tenant_id", "messages.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "conversation_id", "external_id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "in_reply_to_id"),
    )
    op.create_index(
        "ix_messages_tenant_conversation",
        "messages",
        ["tenant_id", "conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "widget_sessions",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_widget_sessions_tenant_id", "widget_sessions", ["tenant_id", "id"], unique=False
    )
    op.create_table(
        "knowledge_gaps",
        sa.Column("question", sa.String(), nullable=False),
        sa.Column("example_message_id", sa.Uuid(), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "answered",
                "ignored",
                name="gap_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("answer_text", sa.String(), nullable=True),
        sa.Column("converted_document_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "converted_document_id"],
            ["documents.tenant_id", "documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "example_message_id"],
            ["messages.tenant_id", "messages.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "question"),
    )
    op.create_index(
        "ix_gaps_tenant_status", "knowledge_gaps", ["tenant_id", "status"], unique=False
    )
    op.create_unique_constraint("uq_agent_runs_tenant_id_id", "agent_runs", ["tenant_id", "id"])
    op.create_foreign_key(
        "fk_message_agent_run",
        "messages",
        "agent_runs",
        ["tenant_id", "agent_run_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_run_message",
        "agent_runs",
        "messages",
        ["tenant_id", "message_id"],
        ["tenant_id", "id"],
        use_alter=True,
    )


def downgrade() -> None:
    op.drop_constraint("fk_run_message", "agent_runs", type_="foreignkey")
    op.drop_constraint("fk_message_agent_run", "messages", type_="foreignkey")
    op.drop_constraint("uq_agent_runs_tenant_id_id", "agent_runs", type_="unique")
    op.drop_index("ix_gaps_tenant_status", table_name="knowledge_gaps")
    op.drop_table("knowledge_gaps")
    op.drop_index("ix_widget_sessions_tenant_id", table_name="widget_sessions")
    op.drop_table("widget_sessions")
    op.drop_index("ix_messages_tenant_conversation", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_rules_tenant_catalog", table_name="pricing_rules")
    op.drop_table("pricing_rules")
    op.drop_index("ix_conversations_tenant_status", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_chunks_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_index("ix_chunks_tenant_document", table_name="chunks")
    op.drop_index(
        "ix_chunks_embedding",
        table_name="chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("chunks")
    op.drop_index("ix_documents_tenant_status", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_customers_tenant_id", table_name="customers")
    op.drop_table("customers")
    op.drop_index("ix_catalog_tsv", table_name="catalog_items", postgresql_using="gin")
    op.drop_index("ix_catalog_tenant_active", table_name="catalog_items")
    op.drop_index(
        "ix_catalog_name_trgm",
        table_name="catalog_items",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_catalog_embedding",
        table_name="catalog_items",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("catalog_items")
    op.drop_index("ix_imports_tenant_id", table_name="catalog_imports")
    op.drop_table("catalog_imports")
