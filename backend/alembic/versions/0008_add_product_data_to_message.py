"""Add product_data to message table.

Revision ID: 0008_add_product_data_to_message
Revises: 0007_product_upload_progress
Create Date: 2026-01-26 11:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0008_add_product_data_to_message"
down_revision = "0007_product_upload_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add product_data column to message table
    op.add_column("message", sa.Column("product_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Remove product_data column from message table
    op.drop_column("message", "product_data")
