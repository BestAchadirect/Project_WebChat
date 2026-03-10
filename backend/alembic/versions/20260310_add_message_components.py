"""Add persisted assistant components to message history.

Revision ID: 20260310_add_message_components
Revises: 20260306_add_facet_governance
Create Date: 2026-03-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260310_add_message_components"
down_revision = "20260306_add_facet_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("message", sa.Column("components", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("message", "components")
