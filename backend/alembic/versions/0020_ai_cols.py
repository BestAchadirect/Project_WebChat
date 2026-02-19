"""add ai hardening columns

Revision ID: 0020_ai_cols
Revises: 0019_idx_restore
Create Date: 2026-02-19 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0020_ai_cols"
down_revision: Union[str, Sequence[str], None] = "0019_idx_restore"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("last_stock_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledge_articles", sa.Column("active_version", sa.Integer(), nullable=True))
    op.add_column("qa_logs", sa.Column("user_feedback", sa.SmallInteger(), nullable=True))
    op.add_column("qa_logs", sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_qa_logs_user_feedback_valid",
        "qa_logs",
        "user_feedback IN (-1, 1)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_qa_logs_user_feedback_valid", "qa_logs", type_="check")
    op.drop_column("qa_logs", "feedback_at")
    op.drop_column("qa_logs", "user_feedback")
    op.drop_column("knowledge_articles", "active_version")
    op.drop_column("products", "last_stock_sync_at")

