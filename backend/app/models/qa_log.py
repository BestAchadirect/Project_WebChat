import uuid
from datetime import datetime
import enum
from sqlalchemy import CheckConstraint, Column, String, DateTime, Enum, SmallInteger
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base

class QAStatus(str, enum.Enum):
    SUCCESS = "success"
    NO_ANSWER = "no_answer"
    FALLBACK = "fallback"
    FAILED = "failed"

class QALog(Base):
    __tablename__ = "qa_logs"
    __table_args__ = (
        CheckConstraint("user_feedback IN (-1, 1)", name="ck_qa_logs_user_feedback_valid"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    question = Column(String, nullable=False)
    answer = Column(String, nullable=True)
    sources = Column(JSONB, default=list) # List of sources cited
    token_usage = Column(JSONB, nullable=True)
    channel = Column(String(32), nullable=True)
    user_feedback = Column(SmallInteger, nullable=True)
    feedback_at = Column(DateTime(timezone=True), nullable=True)
    
    status = Column(Enum(QAStatus), default=QAStatus.SUCCESS, nullable=False)
    error_message = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
