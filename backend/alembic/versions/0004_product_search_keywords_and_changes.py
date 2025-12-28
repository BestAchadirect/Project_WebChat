"""Add product_changes table and search_keywords on products."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_search_kw_changes"
down_revision = "0003_product_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "search_keywords",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY[]::varchar[]"),
        ),
    )

    op.create_table(
        "product_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=True),
        sa.Column("old_values", postgresql.JSONB(), nullable=True),
        sa.Column("new_values", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["upload_id"], ["product_uploads.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
    )
    op.create_index("ix_product_changes_product_id", "product_changes", ["product_id"])
    op.create_index("ix_product_changes_upload_id", "product_changes", ["upload_id"])


def downgrade() -> None:
    op.drop_index("ix_product_changes_upload_id", table_name="product_changes")
    op.drop_index("ix_product_changes_product_id", table_name="product_changes")
    op.drop_table("product_changes")
    op.drop_column("products", "search_keywords")
