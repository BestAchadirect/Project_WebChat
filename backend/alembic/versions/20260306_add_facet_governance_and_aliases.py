"""Add facet governance fields and alias table on existing EAV tables.

Revision ID: 20260306_add_facet_governance
Revises: 20260305_add_klevu_id
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260306_add_facet_governance"
down_revision = "20260305_add_klevu_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attribute_definitions",
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "attribute_definitions",
        sa.Column("tier", sa.String(length=20), nullable=False, server_default=sa.text("'secondary'")),
    )
    op.add_column(
        "attribute_definitions",
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("100")),
    )
    op.add_column(
        "attribute_definitions",
        sa.Column("is_multivalue", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("attribute_definitions", sa.Column("option_cap", sa.Integer(), nullable=True))
    op.add_column(
        "attribute_definitions",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(
        "attribute_definitions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.add_column("product_attribute_values", sa.Column("value_norm", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE product_attribute_values
        SET value_norm = NULLIF(LOWER(BTRIM(value)), '')
        WHERE value IS NOT NULL
        """
    )

    op.create_table(
        "facet_value_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("attribute_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("raw_value_norm", sa.Text(), nullable=False),
        sa.Column("canonical_value", sa.Text(), nullable=False),
        sa.Column("canonical_value_norm", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["attribute_id"],
            ["attribute_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_facet_value_aliases_attribute_id",
        "facet_value_aliases",
        ["attribute_id"],
        unique=False,
    )
    op.create_index(
        "ux_facet_value_aliases_attribute_raw_value_norm",
        "facet_value_aliases",
        ["attribute_id", "raw_value_norm"],
        unique=True,
    )
    op.create_index(
        "ix_facet_value_aliases_attribute_canonical_value_norm",
        "facet_value_aliases",
        ["attribute_id", "canonical_value_norm"],
        unique=False,
    )

    op.create_index(
        "ix_product_attribute_values_attribute_id_value_norm_product_id",
        "product_attribute_values",
        ["attribute_id", "value_norm", "product_id"],
        unique=False,
    )

    op.execute("DROP INDEX IF EXISTS ux_product_attribute_values_product_id_attribute_id")
    op.create_index(
        "ux_product_attribute_values_product_id_attribute_id_value_norm",
        "product_attribute_values",
        ["product_id", "attribute_id", "value_norm"],
        unique=True,
        postgresql_where=sa.text("value_norm IS NOT NULL AND value_norm <> ''"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_product_attribute_values_product_id_attribute_id_value_norm",
        table_name="product_attribute_values",
    )
    op.create_index(
        "ux_product_attribute_values_product_id_attribute_id",
        "product_attribute_values",
        ["product_id", "attribute_id"],
        unique=True,
    )
    op.drop_index(
        "ix_product_attribute_values_attribute_id_value_norm_product_id",
        table_name="product_attribute_values",
    )

    op.drop_index(
        "ix_facet_value_aliases_attribute_canonical_value_norm",
        table_name="facet_value_aliases",
    )
    op.drop_index(
        "ux_facet_value_aliases_attribute_raw_value_norm",
        table_name="facet_value_aliases",
    )
    op.drop_index(
        "ix_facet_value_aliases_attribute_id",
        table_name="facet_value_aliases",
    )
    op.drop_table("facet_value_aliases")

    op.drop_column("product_attribute_values", "value_norm")

    op.drop_column("attribute_definitions", "updated_at")
    op.drop_column("attribute_definitions", "created_at")
    op.drop_column("attribute_definitions", "option_cap")
    op.drop_column("attribute_definitions", "is_multivalue")
    op.drop_column("attribute_definitions", "display_order")
    op.drop_column("attribute_definitions", "tier")
    op.drop_column("attribute_definitions", "is_enabled")
