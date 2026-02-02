"""add eav attribute indexes

Revision ID: 0013_add_eav_indexes
Revises: 0012_eav_product_attributes
Create Date: 2026-02-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0013_add_eav_indexes"
down_revision: Union[str, Sequence[str], None] = "0012_eav_product_attributes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_product_attribute_values_attribute_id_value",
        "product_attribute_values",
        ["attribute_id", "value"],
        unique=False,
    )
    op.create_index(
        "ix_product_attribute_values_product_id_attribute_id",
        "product_attribute_values",
        ["product_id", "attribute_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_product_attribute_values_product_id_attribute_id", table_name="product_attribute_values")
    op.drop_index("ix_product_attribute_values_attribute_id_value", table_name="product_attribute_values")
