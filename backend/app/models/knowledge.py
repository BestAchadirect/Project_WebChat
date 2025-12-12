from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from datetime import datetime
import uuid

from app.db.base import Base
from app.core.config import settings

class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    url = Column(String, nullable=True)
    category = Column(String, nullable=True, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    embeddings = relationship("KnowledgeEmbedding", back_populates="article", cascade="all, delete-orphan")

class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_articles.id"), nullable=False)
    
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(settings.VECTOR_DIMENSIONS), nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    article = relationship("KnowledgeArticle", back_populates="embeddings")
