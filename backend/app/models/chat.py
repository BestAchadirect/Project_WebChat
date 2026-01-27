from sqlalchemy import Column, String, DateTime, ForeignKey, Text, BigInteger, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum

from app.db.base import Base

class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class AppUser(Base):
    __tablename__ = "app_user"

    id = Column(String(64), primary_key=True)  # guest_abc, user_42
    customer_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    magento_customer_id = Column(BigInteger, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")

class Conversation(Base):
    __tablename__ = "conversation"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("app_user.id"), nullable=True)
    
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_message_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    state = Column(JSON, default={}) # AI session memory
    
    # Relationships
    user = relationship("AppUser", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "message"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, ForeignKey("conversation.id"), nullable=False)
    
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    product_data = Column(JSON, nullable=True) # Store carousel items for context
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
