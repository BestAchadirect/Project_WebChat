"""baseline schema"""

from __future__ import annotations

from alembic import op

from app.db.base import Base
import app.models  # noqa: F401

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Intentional no-op: avoid destructive drops on baseline.
    pass
