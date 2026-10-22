"""foundation tenant identity and audit models"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "aa73c6cdbab4"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reviewed: pgvector and trigram search are required by the architecture.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("business_type", sa.String(length=100), nullable=False),
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("logo_url", sa.String(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("widget_public_key", sa.String(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("widget_public_key"),
    )
    op.create_table(
        "agent_runs",
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
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
        sa.CheckConstraint("status IN ('success', 'error', 'invalid')", name="agent_run_status"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_runs_tenant_id_message_id",
        "agent_runs",
        ["tenant_id", "message_id"],
        unique=False,
    )
    op.create_table(
        "tenant_settings",
        sa.Column("tone", sa.String(), nullable=False),
        sa.Column("languages", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("business_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("auto_send_quotes", sa.Boolean(), nullable=False),
        sa.Column("auto_send_limit_paise", sa.BigInteger(), nullable=False),
        sa.Column("max_auto_discount_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("quote_validity_days", sa.Integer(), nullable=False),
        sa.Column("followup_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("handoff_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("owner_notify_whatsapp", sa.Boolean(), nullable=False),
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
        sa.UniqueConstraint("tenant_id"),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.Enum("owner", "staff", "admin", name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("ix_users_tenant_id_id", "users", ["tenant_id", "id"], unique=False)
    op.create_table(
        "refresh_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
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
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_refresh_sessions_tenant_id_id", "refresh_sessions", ["tenant_id", "id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_sessions_tenant_id_id", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
    op.drop_index("ix_users_tenant_id_id", table_name="users")
    op.drop_table("users")
    op.drop_table("tenant_settings")
    op.drop_index("ix_agent_runs_tenant_id_message_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_table("tenants")
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
