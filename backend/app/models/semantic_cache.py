from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.config import settings
from app.db.base import Base


class SemanticCache(Base):
    __tablename__ = "semantic_cache"
    __table_args__ = (
        Index(
            "ix_semantic_cache_lookup",
            "reply_language",
            "target_currency",
            "expires_at",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    query_text = Column(Text, nullable=False)
    embedding = Column(Vector(settings.VECTOR_DIMENSIONS), nullable=False)
    response_json = Column(JSONB, nullable=False)
    reply_language = Column(String, nullable=False)
    target_currency = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)

