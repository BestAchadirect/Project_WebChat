from sqlalchemy import Column, String, Text, BigInteger, JSON, DateTime
from sqlalchemy.sql import func
from app.db.base import Base

class ChatSetting(Base):
    __tablename__ = "chat_setting"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    merchant_id = Column(String(64), nullable=True, index=True) # For future multi-tenancy
    
    title = Column(String(255), nullable=False, default="Jewelry Assistant")
    primary_color = Column(String(50), nullable=False, default="#214166")
    welcome_message = Column(Text, nullable=False, default="Welcome to our wholesale body jewelry support! 👋 How can I help you today?")
    faq_suggestions = Column(JSON, nullable=False, default=[
        "What is your minimum order?",
        "Do you offer custom designs?",
        "What materials do you use?"
    ])
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
