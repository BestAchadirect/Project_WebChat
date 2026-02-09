"""dedupe eav values and add unique constraint

Revision ID: 0014_eav_unique_pairs
Revises: 0013_add_eav_indexes
Create Date: 2026-02-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0014_eav_unique_pairs"
down_revision: Union[str, Sequence[str], None] = "0013_add_eav_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM product_attribute_values a
            USING product_attribute_values b
            WHERE a.product_id = b.product_id
              AND a.attribute_id = b.attribute_id
              AND a.id < b.id
            """
        )
    )
    op.drop_index("ix_product_attribute_values_product_id_attribute_id", table_name="product_attribute_values")
    op.create_index(
        "ux_product_attribute_values_product_id_attribute_id",
        "product_attribute_values",
        ["product_id", "attribute_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_product_attribute_values_product_id_attribute_id", table_name="product_attribute_values")
    op.create_index(
        "ix_product_attribute_values_product_id_attribute_id",
        "product_attribute_values",
        ["product_id", "attribute_id"],
        unique=False,
    )
