from __future__ import annotations

import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class KlevuSyncRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    stopped = "stopped"


class KlevuSyncRun(Base):
    __tablename__ = "klevu_sync_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=func.gen_random_uuid())
    status = Column(Enum(KlevuSyncRunStatus, name="klevu_sync_run_status"), nullable=False, default=KlevuSyncRunStatus.pending)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    page_size = Column(Integer, nullable=False, default=100)
    max_pages = Column(Integer, nullable=True)
    current_offset = Column(Integer, nullable=False, default=0)
    last_success_offset = Column(Integer, nullable=False, default=0)

    fetched_records = Column(Integer, nullable=False, default=0)
    created = Column(Integer, nullable=False, default=0)
    updated = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    backoff_count = Column(Integer, nullable=False, default=0)
    request_count = Column(Integer, nullable=False, default=0)

    error_summary = Column(Text, nullable=True)
    config_snapshot = Column(JSONB, nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False, server_default="false")

    failures = relationship(
        "KlevuSyncFailure",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class KlevuSyncFailure(Base):
    __tablename__ = "klevu_sync_failures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=func.gen_random_uuid())
    run_id = Column(UUID(as_uuid=True), ForeignKey("klevu_sync_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    page_offset = Column(Integer, nullable=False, default=0)
    raw_sku = Column(String, nullable=True)
    canonical_sku = Column(String, nullable=True)
    error_type = Column(String, nullable=False)
    error_message = Column(Text, nullable=False)
    record_payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run = relationship("KlevuSyncRun", back_populates="failures")

