"""Add stock_qty to products for canonical component payloads.

Revision ID: 20260228_add_stock_qty
Revises: 20260227_prod_search_projection
Create Date: 2026-02-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260228_add_stock_qty"
down_revision = "20260227_prod_search_projection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("stock_qty", sa.Integer(), nullable=True))
    op.create_index("ix_products_stock_qty", "products", ["stock_qty"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_products_stock_qty", table_name="products")
    op.drop_column("products", "stock_qty")

