"""backfill ai hardening columns

Revision ID: 0021_ai_backfill
Revises: 0020_ai_cols
Create Date: 2026-02-19 00:00:02.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0021_ai_backfill"
down_revision: Union[str, Sequence[str], None] = "0020_ai_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles ka
            SET active_version = src.max_version
            FROM (
                SELECT article_id, MAX(version) AS max_version
                FROM knowledge_article_versions
                GROUP BY article_id
            ) AS src
            WHERE ka.id = src.article_id
              AND (ka.active_version IS NULL OR ka.active_version <> src.max_version)
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE products
            SET last_stock_sync_at = COALESCE(updated_at, created_at)
            WHERE last_stock_sync_at IS NULL
            """
        )
    )


def downgrade() -> None:
    # Backfill-only migration; do not erase values on downgrade.
    pass

