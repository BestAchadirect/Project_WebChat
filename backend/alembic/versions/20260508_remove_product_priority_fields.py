"""Remove product chat priority fields.

Revision ID: 20260508_drop_product_priority
Revises: 20260417_chunk_enrich
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260508_drop_product_priority"
down_revision = "20260417_chunk_enrich"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("products", "priority")
    op.drop_column("products", "is_featured")


def downgrade() -> None:
    op.add_column(
        "products",
        sa.Column("is_featured", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    op.add_column(
        "products",
        sa.Column("priority", sa.Integer(), nullable=True, server_default=sa.text("0")),
    )
