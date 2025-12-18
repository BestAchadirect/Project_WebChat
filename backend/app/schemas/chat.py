from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any
import uuid


class ProductCard(BaseModel):
    id: uuid.UUID
    object_id: Optional[str] = None
    sku: str
    legacy_sku: List[str] = []
    name: str
    price: float
    currency: str
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    attributes: Dict[str, Any] = {}


class KnowledgeSource(BaseModel):
    source_id: str
    title: str
    content_snippet: str
    category: Optional[str] = None
    relevance: float
    url: Optional[str] = None


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="Unique ID for the user (e.g. guest_123)")
    customer_name: Optional[str] = None
    email: Optional[str] = None
    conversation_id: Optional[int] = None
    message: str
    locale: Optional[str] = "en-US"


class ParsedQuery(BaseModel):
    intent: Literal["search_products", "ask_info", "mixed", "smalltalk", "other"]
    query_text: str
    language: Literal["en", "th", "auto"]
    filters: Dict[str, str] = {}
    price_min: Optional[float] = None
    price_max: Optional[float] = None


class ChatResponse(BaseModel):
    conversation_id: int
    reply_text: str
    product_carousel: List[ProductCard] = []
    follow_up_questions: List[str] = []
    intent: str = "retrieval_router"
    sources: List[KnowledgeSource] = []
