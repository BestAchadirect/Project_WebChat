"""Merge products.name into master_code and drop name.

This keeps API compatibility by allowing the ORM layer to map `Product.name` to `master_code`,
but the database no longer stores a separate `name` column.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_prod_master_code"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Copy name -> master_code for rows that don't have a master_code yet.
    op.execute(
        """
        UPDATE products
        SET master_code = name
        WHERE (master_code IS NULL OR btrim(master_code) = '')
          AND name IS NOT NULL
        """
    )

    # Ensure master_code is always present going forward.
    op.alter_column(
        "products",
        "master_code",
        existing_type=sa.String(),
        nullable=False,
    )

    # Drop the legacy name column.
    op.drop_column("products", "name")


def downgrade() -> None:
    # Re-add name and backfill from master_code.
    op.add_column("products", sa.Column("name", sa.String(), nullable=True))
    op.execute("UPDATE products SET name = master_code WHERE name IS NULL")
    op.alter_column("products", "name", existing_type=sa.String(), nullable=False)

    # Restore original nullability for master_code.
    op.alter_column(
        "products",
        "master_code",
        existing_type=sa.String(),
        nullable=True,
    )
