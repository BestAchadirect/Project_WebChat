from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, Integer, String, Boolean
from sqlalchemy.dialects.postgresql import UUID, ARRAY

from app.db.base import Base


class DocumentStatus(str, enum.Enum):
    """Lifecycle states for uploaded documents."""
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    """Represents a user-uploaded document."""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    file_path = Column(String, nullable=False)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.UPLOADED, nullable=False)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Document Control
    title = Column(String, nullable=True)
    tags = Column(ARRAY(String), default=list)
    category = Column(String, nullable=True)
    is_enabled = Column(Boolean, default=True)
