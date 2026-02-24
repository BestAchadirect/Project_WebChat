from sqlalchemy import Column, String, DateTime, ForeignKey, Text, BigInteger, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime

from app.db.base import Base

class Ticket(Base):
    __tablename__ = "ticket"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("app_user.id"), nullable=False)
    
    description = Column(Text, nullable=False)
    image_url = Column(String(511), nullable=True)
    image_urls = Column(JSON, nullable=True) # List of strings
    status = Column(String(50), default="pending")  # pending, in_progress, resolved, closed
    ai_summary = Column(Text, nullable=True)
    admin_reply = Column(Text, nullable=True)
    admin_replies = Column(JSON, nullable=True)  # List of {"message": str, "created_at": iso-string}
    customer_last_activity_at = Column(DateTime(timezone=True), nullable=True)
    admin_last_seen_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("AppUser")
