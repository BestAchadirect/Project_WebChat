"""Add normalized category taxonomy tables.

Revision ID: 20260304_category_taxonomy
Revises: 20260303_klevu_sync_runs
Create Date: 2026-03-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260304_category_taxonomy"
down_revision = "20260303_klevu_sync_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column(
            "parent_id",
            sa.BigInteger(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_categories_slug", "categories", ["slug"], unique=True)
    op.create_index("ix_categories_label", "categories", ["label"], unique=False)
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"], unique=False)

    op.create_table(
        "product_categories",
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.BigInteger(),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=50), nullable=False, server_default=sa.text("'klevu'")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("product_id", "category_id", name="pk_product_categories"),
    )
    op.create_index("ix_product_categories_category_id", "product_categories", ["category_id"], unique=False)
    op.create_index("ix_product_categories_product_id", "product_categories", ["product_id"], unique=False)
    op.create_index("ix_product_categories_source", "product_categories", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_product_categories_source", table_name="product_categories")
    op.drop_index("ix_product_categories_product_id", table_name="product_categories")
    op.drop_index("ix_product_categories_category_id", table_name="product_categories")
    op.drop_table("product_categories")

    op.drop_index("ix_categories_parent_id", table_name="categories")
    op.drop_index("ix_categories_label", table_name="categories")
    op.drop_index("ix_categories_slug", table_name="categories")
    op.drop_table("categories")
