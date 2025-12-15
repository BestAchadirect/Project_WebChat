from sqlalchemy import Column, Integer, String, DateTime, Text, Enum, UUID
from sqlalchemy.sql import func
import enum
from app.db.base import Base

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskType(str, enum.Enum):
    DOCUMENT_PROCESSING = "document_processing"
    DATA_IMPORT = "data_import"
    EMBEDDING_GENERATION = "embedding_generation"
    PRODUCT_UPDATE = "product_update"

class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=func.gen_random_uuid())
    task_type = Column(Enum(TaskType), nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    description = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    progress = Column(Integer, default=0)  # 0-100
    task_metadata = Column(Text, nullable=True)  # JSON string for additional data