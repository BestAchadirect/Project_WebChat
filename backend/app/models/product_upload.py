from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class ProductUploadStatus(str, enum.Enum):
    """Status of a product import upload."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProductUpload(Base):
    """Tracks CSV uploads for product imports."""
    __tablename__ = "product_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), nullable=True)
    status = Column(Enum(ProductUploadStatus), default=ProductUploadStatus.PENDING, nullable=False)
    error_message = Column(Text, nullable=True)
    imported_products = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    products = relationship("Product", back_populates="upload")
