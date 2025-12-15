from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from datetime import datetime
import uuid
import enum

from app.db.base import Base
from app.core.config import settings

class KnowledgeUploadStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class KnowledgeUpload(Base):
    __tablename__ = "knowledge_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    file_path = Column(String, nullable=False)
    uploaded_by = Column(String, nullable=True)
    status = Column(Enum(KnowledgeUploadStatus), default=KnowledgeUploadStatus.PENDING, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    articles = relationship("KnowledgeArticle", back_populates="upload", cascade="all, delete")

    @property
    def articles_count(self) -> int:
        return len(self.articles or [])

class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    url = Column(String, nullable=True)
    category = Column(String, nullable=True, index=True)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_uploads.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    embeddings = relationship("KnowledgeEmbedding", back_populates="article", cascade="all, delete-orphan")
    upload = relationship("KnowledgeUpload", back_populates="articles")

class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_articles.id"), nullable=False)
    
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(settings.VECTOR_DIMENSIONS), nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    article = relationship("KnowledgeArticle", back_populates="embeddings")
