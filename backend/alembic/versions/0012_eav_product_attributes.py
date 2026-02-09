"""add eav tables for product attributes

Revision ID: 0012_eav_product_attributes
Revises: 0011_add_banners
Create Date: 2026-02-02 00:00:00.000000

"""
from typing import Sequence, Union, List, Tuple

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0012_eav_product_attributes"
down_revision: Union[str, Sequence[str], None] = "0011_add_banners"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ATTRIBUTES: List[Tuple[str, str, str]] = [
    ("jewelry_type", "Jewelry Type", "string"),
    ("material", "Material", "string"),
    ("length", "Length", "string"),
    ("size", "Size", "string"),
    ("cz_color", "CZ Color", "string"),
    ("design", "Design", "string"),
    ("crystal_color", "Crystal Color", "string"),
    ("color", "Color", "string"),
    ("gauge", "Gauge", "string"),
    ("size_in_pack", "Size In Pack", "integer"),
    ("rack", "Rack", "string"),
    ("height", "Height", "string"),
    ("packing_option", "Packing Option", "string"),
    ("pincher_size", "Pincher Size", "string"),
    ("ring_size", "Ring Size", "string"),
    ("quantity_in_bulk", "Quantity In Bulk", "integer"),
    ("opal_color", "Opal Color", "string"),
    ("threading", "Threading", "string"),
    ("outer_diameter", "Outer Diameter", "string"),
    ("pearl_color", "Pearl Color", "string"),
]

INT_ATTRIBUTES = {"size_in_pack", "quantity_in_bulk"}


def _expected_columns() -> List[str]:
    return [name for name, _display, _dtype in ATTRIBUTES]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    product_columns = {c["name"] for c in inspector.get_columns("products")}
    missing = [c for c in _expected_columns() if c not in product_columns]
    if missing:
        raise RuntimeError(f"Missing columns in products table: {', '.join(missing)}")

    op.create_table(
        "attribute_definitions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("data_type", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attribute_definitions_name",
        "attribute_definitions",
        ["name"],
        unique=True,
    )

    op.create_table(
        "product_attribute_values",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribute_id", sa.BigInteger(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attribute_id"], ["attribute_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_attribute_values_product_id",
        "product_attribute_values",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_attribute_values_attribute_id",
        "product_attribute_values",
        ["attribute_id"],
        unique=False,
    )

    attr_table = sa.table(
        "attribute_definitions",
        sa.column("name", sa.String),
        sa.column("display_name", sa.String),
        sa.column("data_type", sa.String),
    )
    op.bulk_insert(
        attr_table,
        [
            {"name": name, "display_name": display, "data_type": dtype}
            for name, display, dtype in ATTRIBUTES
        ],
    )

    for name, _display, _dtype in ATTRIBUTES:
        conn.execute(
            sa.text(
                f"""
                INSERT INTO product_attribute_values (product_id, attribute_id, value)
                SELECT p.id, ad.id, CAST(p.{name} AS TEXT)
                FROM products p
                JOIN attribute_definitions ad ON ad.name = :name
                WHERE p.{name} IS NOT NULL
                """
            ),
            {"name": name},
        )

    for name, _display, _dtype in ATTRIBUTES:
        op.drop_column("products", name)


def downgrade() -> None:
    conn = op.get_bind()
    for name, _display, _dtype in ATTRIBUTES:
        if name in INT_ATTRIBUTES:
            op.add_column("products", sa.Column(name, sa.Integer(), nullable=True))
        else:
            op.add_column("products", sa.Column(name, sa.String(), nullable=True))

    for name, _display, _dtype in ATTRIBUTES:
        if name in INT_ATTRIBUTES:
            value_expr = "pav.value::INTEGER"
        else:
            value_expr = "pav.value"
        conn.execute(
            sa.text(
                f"""
                UPDATE products p
                SET {name} = {value_expr}
                FROM attribute_definitions ad
                JOIN product_attribute_values pav ON pav.attribute_id = ad.id
                WHERE ad.name = :name
                  AND pav.product_id = p.id
                """
            ),
            {"name": name},
        )

    op.create_index("ix_products_jewelry_type", "products", ["jewelry_type"], unique=False)
    op.create_index("ix_products_material", "products", ["material"], unique=False)

    op.drop_index("ix_product_attribute_values_attribute_id", table_name="product_attribute_values")
    op.drop_index("ix_product_attribute_values_product_id", table_name="product_attribute_values")
    op.drop_table("product_attribute_values")

    op.drop_index("ix_attribute_definitions_name", table_name="attribute_definitions")
    op.drop_table("attribute_definitions")
