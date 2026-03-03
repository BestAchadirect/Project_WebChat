"""Add Klevu sync run and failure tracking tables.

Revision ID: 20260303_klevu_sync_runs
Revises: 20260228_add_stock_qty
Create Date: 2026-03-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260303_klevu_sync_runs"
down_revision = "20260228_add_stock_qty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum idempotently because some environments may already have the type.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE t.typname = 'klevu_sync_run_status'
            ) THEN
                CREATE TYPE klevu_sync_run_status AS ENUM (
                    'pending',
                    'running',
                    'completed',
                    'failed',
                    'cancelled',
                    'stopped'
                );
            END IF;
        END
        $$;
        """
    )

    klevu_run_status = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "stopped",
        name="klevu_sync_run_status",
        create_type=False,
    )

    op.create_table(
        "klevu_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("status", klevu_run_status, nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("page_size", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("max_pages", sa.Integer(), nullable=True),
        sa.Column("current_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_success_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("backoff_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_index("ix_klevu_sync_runs_status", "klevu_sync_runs", ["status"], unique=False)
    op.create_index("ix_klevu_sync_runs_started_at", "klevu_sync_runs", ["started_at"], unique=False)
    op.create_index("ix_klevu_sync_runs_cancel_requested", "klevu_sync_runs", ["cancel_requested"], unique=False)

    op.create_table(
        "klevu_sync_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("klevu_sync_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_sku", sa.String(), nullable=True),
        sa.Column("canonical_sku", sa.String(), nullable=True),
        sa.Column("error_type", sa.String(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("record_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_klevu_sync_failures_run_id", "klevu_sync_failures", ["run_id"], unique=False)
    op.create_index("ix_klevu_sync_failures_page_offset", "klevu_sync_failures", ["page_offset"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_klevu_sync_failures_page_offset", table_name="klevu_sync_failures")
    op.drop_index("ix_klevu_sync_failures_run_id", table_name="klevu_sync_failures")
    op.drop_table("klevu_sync_failures")

    op.drop_index("ix_klevu_sync_runs_cancel_requested", table_name="klevu_sync_runs")
    op.drop_index("ix_klevu_sync_runs_started_at", table_name="klevu_sync_runs")
    op.drop_index("ix_klevu_sync_runs_status", table_name="klevu_sync_runs")
    op.drop_table("klevu_sync_runs")

    op.execute("DROP TYPE IF EXISTS klevu_sync_run_status")
