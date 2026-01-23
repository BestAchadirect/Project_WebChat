from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class ProductUploadStatus(str, enum.Enum):
    """Status of a product import upload."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def _enum_values(enum_cls) -> list[str]:
    return [e.value for e in enum_cls]


class ProductUpload(Base):
    """Tracks CSV uploads for product imports."""
    __tablename__ = "product_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), nullable=True)
    status = Column(
        Enum(
            ProductUploadStatus,
            name="product_upload_status",
            values_callable=_enum_values,
        ),
        default=ProductUploadStatus.PENDING,
        nullable=False,
    )
    error_message = Column(Text, nullable=True)
    imported_products = Column(Integer, default=0)
    
    # Progress tracking for large imports
    total_rows = Column(Integer, nullable=True)
    rows_processed = Column(Integer, default=0)
    progress_percentage = Column(Integer, default=0)
    error_log = Column(JSONB, default=list)  # Store detailed error information
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    products = relationship("Product", back_populates="upload")
