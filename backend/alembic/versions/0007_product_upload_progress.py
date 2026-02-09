"""Add progress tracking to product_uploads table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0007_product_upload_progress"
down_revision = "0006_semantic_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add progress tracking columns
    op.add_column("product_uploads", sa.Column("total_rows", sa.Integer(), nullable=True))
    op.add_column("product_uploads", sa.Column("rows_processed", sa.Integer(), server_default="0", nullable=False))
    op.add_column("product_uploads", sa.Column("progress_percentage", sa.Integer(), server_default="0", nullable=False))
    op.add_column("product_uploads", sa.Column("error_log", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    # Remove progress tracking columns
    op.drop_column("product_uploads", "error_log")
    op.drop_column("product_uploads", "progress_percentage")
    op.drop_column("product_uploads", "rows_processed")
    op.drop_column("product_uploads", "total_rows")
