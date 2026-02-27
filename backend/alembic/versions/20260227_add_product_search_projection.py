"""Add product search projection table for SQL-first chat retrieval.

Revision ID: 20260227_prod_search_projection
Revises: 20260226_baseline_squash
Create Date: 2026-02-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260227_prod_search_projection"
down_revision = "20260226_baseline_squash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_search_projection",
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("sku_norm", sa.String(length=255), nullable=False),
        sa.Column("material_norm", sa.String(length=255), nullable=True),
        sa.Column("jewelry_type_norm", sa.String(length=255), nullable=True),
        sa.Column("gauge_norm", sa.String(length=64), nullable=True),
        sa.Column("threading_norm", sa.String(length=128), nullable=True),
        sa.Column("color_norm", sa.String(length=255), nullable=True),
        sa.Column("opal_color_norm", sa.String(length=255), nullable=True),
        sa.Column("search_text_norm", sa.Text(), nullable=True),
        sa.Column("stock_status_norm", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_index(
        "ix_product_search_projection_active_filters",
        "product_search_projection",
        ["is_active", "material_norm", "jewelry_type_norm", "gauge_norm", "threading_norm", "color_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_sku_active",
        "product_search_projection",
        ["sku_norm", "is_active"],
        unique=False,
    )
    op.create_index("ix_product_search_projection_sku_norm", "product_search_projection", ["sku_norm"], unique=False)
    op.create_index(
        "ix_product_search_projection_material_norm",
        "product_search_projection",
        ["material_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_jewelry_type_norm",
        "product_search_projection",
        ["jewelry_type_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_gauge_norm",
        "product_search_projection",
        ["gauge_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_threading_norm",
        "product_search_projection",
        ["threading_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_color_norm",
        "product_search_projection",
        ["color_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_opal_color_norm",
        "product_search_projection",
        ["opal_color_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_stock_status_norm",
        "product_search_projection",
        ["stock_status_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_is_active",
        "product_search_projection",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_product_search_projection_is_active", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_stock_status_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_opal_color_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_color_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_threading_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_gauge_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_jewelry_type_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_material_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_sku_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_sku_active", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_active_filters", table_name="product_search_projection")
    op.drop_table("product_search_projection")
