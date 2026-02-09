"""add qa_log channel

Revision ID: 0010_add_qa_log_channel
Revises: 0009_add_token_usage_tracking
Create Date: 2026-01-28 17:40:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010_add_qa_log_channel"
down_revision: Union[str, Sequence[str], None] = "0009_add_token_usage_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("qa_logs", sa.Column("channel", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("qa_logs", "channel")
