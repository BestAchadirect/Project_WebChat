"""add chat_setting table

Revision ID: 188dfb4cb03d
Revises: 0010_add_qa_log_channel
Create Date: 2026-01-28 17:41:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "188dfb4cb03d"
down_revision: Union[str, Sequence[str], None] = "0010_add_qa_log_channel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_setting",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("merchant_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("primary_color", sa.String(length=50), nullable=False),
        sa.Column("welcome_message", sa.Text(), nullable=False),
        sa.Column("faq_suggestions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_setting_merchant_id"), "chat_setting", ["merchant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_setting_merchant_id"), table_name="chat_setting")
    op.drop_table("chat_setting")
