"""
Add projection facet columns for body_part, presentation_type, and feature.

Revision ID: 20260408_add_proj_facets
Revises: 20260310_add_message_components
Create Date: 2026-04-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260408_add_proj_facets"
down_revision = "20260310_add_message_components"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_search_projection",
        sa.Column("presentation_type_norm", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "product_search_projection",
        sa.Column("body_part_norm", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "product_search_projection",
        sa.Column("feature_norm", sa.String(length=255), nullable=True),
    )

    op.create_index(
        "ix_product_search_projection_presentation_type_norm",
        "product_search_projection",
        ["presentation_type_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_body_part_norm",
        "product_search_projection",
        ["body_part_norm"],
        unique=False,
    )
    op.create_index(
        "ix_product_search_projection_feature_norm",
        "product_search_projection",
        ["feature_norm"],
        unique=False,
    )
    op.drop_index("ix_product_search_projection_active_filters", table_name="product_search_projection")
    op.create_index(
        "ix_product_search_projection_active_filters",
        "product_search_projection",
        [
            "is_active",
            "material_norm",
            "jewelry_type_norm",
            "presentation_type_norm",
            "body_part_norm",
            "feature_norm",
            "gauge_norm",
            "threading_norm",
            "color_norm",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_product_search_projection_active_filters", table_name="product_search_projection")
    op.create_index(
        "ix_product_search_projection_active_filters",
        "product_search_projection",
        ["is_active", "material_norm", "jewelry_type_norm", "gauge_norm", "threading_norm", "color_norm"],
        unique=False,
    )
    op.drop_index("ix_product_search_projection_feature_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_body_part_norm", table_name="product_search_projection")
    op.drop_index("ix_product_search_projection_presentation_type_norm", table_name="product_search_projection")
    op.drop_column("product_search_projection", "feature_norm")
    op.drop_column("product_search_projection", "body_part_norm")
    op.drop_column("product_search_projection", "presentation_type_norm")
