from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any
import uuid


class ProductCard(BaseModel):
    id: uuid.UUID
    object_id: Optional[str] = None
    sku: str
    legacy_sku: List[str] = []
    name: str
    description: Optional[str] = None
    price: float
    currency: str
    stock_status: Optional[str] = None
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    attributes: Dict[str, Any] = {}


class KnowledgeSource(BaseModel):
    source_id: str
    chunk_id: Optional[str] = None
    title: str
    content_snippet: str
    category: Optional[str] = None
    relevance: float
    url: Optional[str] = None
    distance: Optional[float] = None
    rerank_score: Optional[float] = Field(default=None, exclude=True)
    query_hint: Optional[str] = Field(default=None, exclude=True)


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="Unique ID for the user (e.g. guest_123)")
    customer_name: Optional[str] = None
    email: Optional[str] = None
    conversation_id: Optional[int] = None
    message: str
    locale: Optional[str] = "en-US"


class ChatContext(BaseModel):
    text: str
    is_question_like: bool
    looks_like_product: bool
    has_store_intent: bool
    is_policy_intent: bool
    policy_topic_count: int
    sku_token: Optional[str] = None
    requested_currency: Optional[str] = None

    @classmethod
    def from_request(
        cls,
        *,
        text: str,
        is_question_like: bool,
        looks_like_product: bool,
        has_store_intent: bool,
        is_policy_intent: bool,
        policy_topic_count: int,
        sku_token: Optional[str],
        requested_currency: Optional[str],
    ) -> "ChatContext":
        return cls(
            text=text,
            is_question_like=is_question_like,
            looks_like_product=looks_like_product,
            has_store_intent=has_store_intent,
            is_policy_intent=is_policy_intent,
            policy_topic_count=policy_topic_count,
            sku_token=sku_token,
            requested_currency=requested_currency,
        )


class RouteDecision(BaseModel):
    route: Literal["smalltalk", "general_chat", "product", "knowledge", "mixed", "clarify", "fallback_general"]
    reason: str


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
    carousel_msg: Optional[str] = None
    product_carousel: List[ProductCard] = []
    follow_up_questions: List[str] = []
    intent: str = "retrieval_router"
    sources: List[KnowledgeSource] = []
    debug: Dict[str, Any] = Field(default_factory=dict)
    view_button_text: str = "View Product Details"
    material_label: str = "Material"
    jewelry_type_label: str = "Jewelry Type"
