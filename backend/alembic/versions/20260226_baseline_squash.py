"""Baseline squash after migration reset.

Revision ID: 20260226_baseline_squash
Revises: None
Create Date: 2026-02-26
"""

from __future__ import annotations

from pathlib import Path
import sys

from alembic import op


# Ensure `app.*` imports resolve when Alembic loads this file.
BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.db.base import Base  # noqa: E402
import app.models  # noqa: F401,E402


# revision identifiers, used by Alembic.
revision = "20260226_baseline_squash"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Baseline downgrade is intentionally a no-op.
    pass
