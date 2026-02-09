from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.config import settings
from app.db.base import Base


class SemanticCache(Base):
    __tablename__ = "semantic_cache"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    query_text = Column(Text, nullable=False)
    embedding = Column(Vector(settings.VECTOR_DIMENSIONS), nullable=False)
    response_json = Column(JSONB, nullable=False)
    reply_language = Column(String, nullable=False)
    target_currency = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)

