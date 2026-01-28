"""add token usage tracking

Revision ID: 0009_add_token_usage_tracking
Revises: 0008_add_product_data_to_message
Create Date: 2026-01-28 17:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0009_add_token_usage_tracking"
down_revision: Union[str, Sequence[str], None] = "0008_add_product_data_to_message"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("message", sa.Column("token_usage", sa.JSON(), nullable=True))
    op.add_column("qa_logs", sa.Column("token_usage", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("qa_logs", "token_usage")
    op.drop_column("message", "token_usage")
