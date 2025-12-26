"""Add product_groups table and group_id on products."""

from __future__ import annotations

from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_product_groups"
down_revision = "0002_prod_master_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("master_code", sa.String(), nullable=False, unique=True),
        sa.Column("display_title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    op.add_column("products", sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "products_group_id_fkey",
        "products",
        "product_groups",
        ["group_id"],
        ["id"],
    )

    # Ensure master_code is populated for grouping.
    op.execute(
        """
        UPDATE products
        SET master_code = sku
        WHERE master_code IS NULL OR btrim(master_code) = ''
        """
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT DISTINCT master_code
            FROM products
            WHERE master_code IS NOT NULL AND btrim(master_code) <> ''
            """
        )
    ).fetchall()

    now = datetime.utcnow()
    group_rows = []
    group_map = {}
    for row in rows:
        master_code = row[0]
        group_id = uuid.uuid4()
        group_map[master_code] = group_id
        group_rows.append(
            {
                "id": group_id,
                "master_code": master_code,
                "display_title": None,
                "created_at": now,
                "updated_at": now,
            }
        )

    if group_rows:
        product_groups_table = sa.table(
            "product_groups",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("master_code", sa.String()),
            sa.column("display_title", sa.String()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        )
        op.bulk_insert(product_groups_table, group_rows)

        for master_code, group_id in group_map.items():
            bind.execute(
                sa.text(
                    """
                    UPDATE products
                    SET group_id = :group_id
                    WHERE master_code = :master_code
                    """
                ),
                {"group_id": group_id, "master_code": master_code},
            )

    op.alter_column("products", "group_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("products_group_id_fkey", "products", type_="foreignkey")
    op.drop_column("products", "group_id")
    op.drop_table("product_groups")
