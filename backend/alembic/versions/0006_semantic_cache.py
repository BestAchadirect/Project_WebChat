"""Add semantic cache table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0006_semantic_cache"
down_revision = "0005_drop_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reply_language", sa.String(), nullable=False),
        sa.Column("target_currency", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_semantic_cache_lookup",
        "semantic_cache",
        ["reply_language", "target_currency", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_semantic_cache_lookup", table_name="semantic_cache")
    op.drop_table("semantic_cache")
