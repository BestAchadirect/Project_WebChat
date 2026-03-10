"""Add klevu_id column to products.

Revision ID: 20260305_add_klevu_id
Revises: 20260304_category_taxonomy
Create Date: 2026-03-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260305_add_klevu_id"
down_revision = "20260304_category_taxonomy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("klevu_id", sa.String(), nullable=True))
    op.create_index("ix_products_klevu_id", "products", ["klevu_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_products_klevu_id", table_name="products")
    op.drop_column("products", "klevu_id")

