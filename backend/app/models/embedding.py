from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from datetime import datetime
import uuid

from app.db.base import Base
from app.core.config import settings

class Embedding(Base):
    __tablename__ = "embeddings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    
    # Chunk information
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)  # Order within document
    
    # Vector embedding
    embedding = Column(Vector(settings.VECTOR_DIMENSIONS), nullable=False)
    
    # Metadata
    chunk_metadata = Column(Text, nullable=True)  # JSON string for additional metadata
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    document = relationship("Document", back_populates="embeddings")
