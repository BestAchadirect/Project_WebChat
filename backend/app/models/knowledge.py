from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum, Integer, UniqueConstraint
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
    active_version = Column(Integer, nullable=True)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_uploads.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    embeddings = relationship("KnowledgeEmbedding", back_populates="article", cascade="all, delete-orphan")
    upload = relationship("KnowledgeUpload", back_populates="articles")
    versions = relationship("KnowledgeArticleVersion", back_populates="article", cascade="all, delete-orphan")
    chunks = relationship("KnowledgeChunk", back_populates="article", cascade="all, delete-orphan")

class KnowledgeArticleVersion(Base):
    __tablename__ = "knowledge_article_versions"
    __table_args__ = (
        UniqueConstraint('article_id', 'version', name='uq_article_version'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_articles.id"), nullable=False)
    version = Column(Integer, nullable=False)
    content_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(String, nullable=True)

    # Relationships
    article = relationship("KnowledgeArticle", back_populates="versions")

class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint('article_id', 'version', 'chunk_index', name='uq_chunk_index'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_articles.id"), nullable=False)
    version = Column(Integer, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    article = relationship("KnowledgeArticle", back_populates="chunks")
    embeddings = relationship("KnowledgeEmbedding", back_populates="chunk", cascade="all, delete-orphan")
    tags = relationship("KnowledgeChunkTag", back_populates="chunk", cascade="all, delete-orphan")

class KnowledgeChunkTag(Base):
    __tablename__ = "knowledge_chunk_tags"
    
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_chunks.id"), primary_key=True)
    tag = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    chunk = relationship("KnowledgeChunk", back_populates="tags")

class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_articles.id"), nullable=False)
    
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(settings.VECTOR_DIMENSIONS), nullable=False)
    
    # New fields
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_chunks.id"), nullable=True)
    model = Column(String, nullable=True)
    version = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    article = relationship("KnowledgeArticle", back_populates="embeddings")
    chunk = relationship("KnowledgeChunk", back_populates="embeddings")
