"""add ticket notification timestamps

Revision ID: 0018_ticket_notify_ts
Revises: 0017_add_admin_replies_to_ticket
Create Date: 2026-02-18 00:00:02.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0018_ticket_notify_ts"
down_revision: Union[str, Sequence[str], None] = "0017_add_admin_replies_to_ticket"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use IF NOT EXISTS so reruns are safe if a previous attempt partially applied.
    op.execute(
        """
        ALTER TABLE ticket
        ADD COLUMN IF NOT EXISTS customer_last_activity_at TIMESTAMPTZ NULL
        """
    )
    op.execute(
        """
        ALTER TABLE ticket
        ADD COLUMN IF NOT EXISTS admin_last_seen_at TIMESTAMPTZ NULL
        """
    )

    # Baseline existing rows as already seen by admin to avoid false notifications after rollout.
    op.execute(
        """
        UPDATE ticket
        SET customer_last_activity_at = COALESCE(updated_at, created_at)
        WHERE customer_last_activity_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE ticket
        SET admin_last_seen_at = customer_last_activity_at
        WHERE admin_last_seen_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ticket
        DROP COLUMN IF EXISTS admin_last_seen_at
        """
    )
    op.execute(
        """
        ALTER TABLE ticket
        DROP COLUMN IF EXISTS customer_last_activity_at
        """
    )
