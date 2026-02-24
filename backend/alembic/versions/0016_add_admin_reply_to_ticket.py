"""add admin_reply column to ticket

Revision ID: 0016_add_admin_reply_to_ticket
Revises: 115cd2c18a84
Create Date: 2026-02-18 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0016_add_admin_reply_to_ticket"
down_revision: Union[str, Sequence[str], None] = "115cd2c18a84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ticket", sa.Column("admin_reply", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ticket", "admin_reply")
