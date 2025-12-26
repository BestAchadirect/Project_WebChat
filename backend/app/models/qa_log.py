import uuid
from datetime import datetime
import enum
from sqlalchemy import Column, String, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base

class QAStatus(str, enum.Enum):
    SUCCESS = "success"
    NO_ANSWER = "no_answer"
    FALLBACK = "fallback"
    FAILED = "failed"

class QALog(Base):
    __tablename__ = "qa_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    question = Column(String, nullable=False)
    answer = Column(String, nullable=True)
    sources = Column(JSONB, default=list) # List of sources cited
    
    status = Column(Enum(QAStatus), default=QAStatus.SUCCESS, nullable=False)
    error_message = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
