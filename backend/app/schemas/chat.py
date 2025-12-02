from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from app.schemas.product import ProductCarouselItem

# Chat Message Schemas
class ChatMessage(BaseModel):
    """Single message in chat history."""
    role: str  # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    """Request to chat endpoint."""
    message: str
    session_id: Optional[str] = None
    tenant_id: UUID
    history: Optional[List[ChatMessage]] = []

class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    message: str
    session_id: str
    intent: Optional[str] = None  # "product", "faq", "both"
    products: Optional[List[ProductCarouselItem]] = None
    sources: Optional[List[Dict[str, Any]]] = None  # FAQ sources
    metadata: Optional[Dict[str, Any]] = None

# Intent Classification
class IntentClassification(BaseModel):
    """Result of intent classification."""
    intent: str  # "product", "faq", "both", "general"
    confidence: float
    reasoning: Optional[str] = None
