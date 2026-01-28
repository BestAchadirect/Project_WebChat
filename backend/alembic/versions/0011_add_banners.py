"""add banner table

Revision ID: 0011_add_banners
Revises: 188dfb4cb03d
Create Date: 2026-01-28 17:22:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0011_add_banners"
down_revision: Union[str, Sequence[str], None] = "188dfb4cb03d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "banner",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("image_url", sa.String(length=512), nullable=False),
        sa.Column("link_url", sa.String(length=1024), nullable=True),
        sa.Column("alt_text", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("banner")
