"""restore critical indexes removed by migration drift

Revision ID: 0019_idx_restore
Revises: 0018_ticket_notify_ts
Create Date: 2026-02-19 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0019_idx_restore"
down_revision: Union[str, Sequence[str], None] = "0018_ticket_notify_ts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_indexes() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_semantic_cache_lookup
            ON semantic_cache (reply_language, target_currency, expires_at)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_message_conversation_id
            ON message (conversation_id)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_product_attribute_values_attribute_id_value
            ON product_attribute_values (attribute_id, value)
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_product_attribute_values_product_id_attribute_id
            ON product_attribute_values (product_id, attribute_id)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_knowledge_embeddings_chunk_id
            ON knowledge_embeddings (chunk_id)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_knowledge_embeddings_article_id
            ON knowledge_embeddings (article_id)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_knowledge_embeddings_embedding_hnsw
            ON knowledge_embeddings USING hnsw (embedding vector_cosine_ops)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_product_embeddings_embedding_hnsw
            ON product_embeddings USING hnsw (embedding vector_cosine_ops)
            """
        )


def _drop_indexes() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_product_embeddings_embedding_hnsw")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_knowledge_embeddings_embedding_hnsw")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_knowledge_embeddings_article_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_knowledge_embeddings_chunk_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ux_product_attribute_values_product_id_attribute_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_product_attribute_values_attribute_id_value")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_message_conversation_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_semantic_cache_lookup")


def upgrade() -> None:
    # Remove duplicates before restoring unique pair index.
    op.execute(
        sa.text(
            """
            DELETE FROM product_attribute_values a
            USING product_attribute_values b
            WHERE a.product_id = b.product_id
              AND a.attribute_id = b.attribute_id
              AND a.id < b.id
            """
        )
    )
    _create_indexes()


def downgrade() -> None:
    _drop_indexes()

