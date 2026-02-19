"""phase1 product embedding performance indexes

Revision ID: 0022_prod_embed_perf
Revises: 0021_ai_backfill
Create Date: 2026-02-19 00:00:03.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0022_prod_embed_perf"
down_revision: Union[str, Sequence[str], None] = "0021_ai_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_indexes() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_prod_emb_pid_model
            ON product_embeddings (product_id, model)
            WHERE model IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_products_product_upload_id
            ON products (product_upload_id)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_product_changes_upload_product
            ON product_changes (upload_id, product_id)
            """
        )


def _drop_indexes() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_product_changes_upload_product")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_products_product_upload_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ux_prod_emb_pid_model")


def upgrade() -> None:
    # Keep the newest embedding per (product_id, model) before creating unique index.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY product_id, model
                        ORDER BY created_at DESC NULLS LAST, id DESC
                    ) AS row_num
                FROM product_embeddings
                WHERE model IS NOT NULL
            )
            DELETE FROM product_embeddings pe
            USING ranked r
            WHERE pe.id = r.id
              AND r.row_num > 1
            """
        )
    )
    _create_indexes()


def downgrade() -> None:
    _drop_indexes()

