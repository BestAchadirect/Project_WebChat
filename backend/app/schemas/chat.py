import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


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
    search_text: Optional[str] = Field(default=None, exclude=True)


class KnowledgeSource(BaseModel):
    source_id: str
    chunk_id: Optional[str] = None
    title: str
    summary: Optional[str] = None
    content_snippet: str
    category: Optional[str] = None
    relevance: float
    url: Optional[str] = None
    distance: Optional[float] = None
    query_hint: Optional[str] = Field(default=None, exclude=True)


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="Unique ID for the user (e.g. guest_123)")
    customer_name: Optional[str] = None
    email: Optional[str] = None
    conversation_id: Optional[int] = None
    message: str
    locale: Optional[str] = "en-US"
    client_action: Optional[str] = None
    client_action_payload: Dict[str, Any] = Field(default_factory=dict)


class ChatContext(BaseModel):
    text: str
    is_question_like: bool
    looks_like_product: bool
    has_store_signal: bool
    is_policy_like: bool
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
        has_store_signal: bool,
        is_policy_like: bool,
        policy_topic_count: int,
        sku_token: Optional[str],
        requested_currency: Optional[str],
    ) -> "ChatContext":
        return cls(
            text=text,
            is_question_like=is_question_like,
            looks_like_product=looks_like_product,
            has_store_signal=has_store_signal,
            is_policy_like=is_policy_like,
            policy_topic_count=policy_topic_count,
            sku_token=sku_token,
            requested_currency=requested_currency,
        )


class ChatRouting(BaseModel):
    workflow: Literal[
        "catalog",
        "knowledge",
        "off_topic",
        "fallback",
    ] = (
        "fallback"
    )
    execution_mode: Literal["component", "agentic"] = "component"
    needs_products: bool = False
    needs_knowledge: bool = False
    needs_clarification: bool = False
    store_overview_request: bool = False
    reason: str = ""
    confidence: float = 0.0
    selection_source: str = ""


class ChatComponentType(str, Enum):
    QUERY_SUMMARY = "query_summary"
    PRODUCT_CARDS = "product_cards"
    PRODUCT_DETAIL = "product_detail"
    CLARIFY = "clarify"
    KNOWLEDGE_ANSWER = "knowledge_answer"
    ERROR = "error"
    ASSISTANT_MESSAGE = "assistant_message"
    QUICK_REPLIES = "quick_replies"


class ChatComponent(BaseModel):
    type: ChatComponentType
    data: Dict[str, Any] = Field(default_factory=dict)


def _component_type_value(component: ChatComponent) -> str:
    raw_type = getattr(component, "type", "")
    return str(getattr(raw_type, "value", raw_type) or "").strip().lower()


def product_card_to_component_payload(card: ProductCard) -> Dict[str, Any]:
    attributes = dict(card.attributes or {})
    return {
        "product_id": str(card.id),
        "object_id": card.object_id,
        "sku": card.sku,
        "title": card.name,
        "description": card.description,
        "price": float(card.price),
        "currency": card.currency,
        "in_stock": str(card.stock_status or "").strip().lower() == "in_stock",
        "stock_qty": getattr(card, "stock_qty", None),
        "image_url": card.image_url,
        "product_url": card.product_url,
        "material": str(attributes.get("material") or "").strip(),
        "gauge": str(attributes.get("gauge") or "").strip(),
        "attributes": attributes,
    }


def assistant_message_component(reply_text: str) -> Optional["ChatComponent"]:
    text = str(reply_text or "").strip()
    if not text:
        return None
    return ChatComponent(
        type=ChatComponentType.ASSISTANT_MESSAGE,
        data={"text": text},
    )


def product_cards_component(
    product_carousel: Optional[List[ProductCard]],
) -> Optional["ChatComponent"]:
    cards = list(product_carousel or [])
    if not cards:
        return None
    return ChatComponent(
        type=ChatComponentType.PRODUCT_CARDS,
        data={"cards": [product_card_to_component_payload(card) for card in cards]},
    )


def quick_replies_component(items: List[Any]) -> Optional["ChatComponent"]:
    clean_items: List[Any] = []
    for raw in list(items or []):
        if isinstance(raw, dict):
            label = str(
                raw.get("label") or raw.get("text") or raw.get("question") or raw.get("message") or ""
            ).strip()
            if not label:
                continue
            item = dict(raw)
            item["label"] = label
            clean_items.append(item)
            continue
        text = str(raw or "").strip()
        if text:
            clean_items.append(text)
    if not clean_items:
        return None
    return ChatComponent(
        type=ChatComponentType.QUICK_REPLIES,
        data={"items": clean_items},
    )


def _augment_chat_components(
    *,
    components: List[ChatComponent],
    reply_text: str = "",
    product_carousel: Optional[List[ProductCard]] = None,
) -> List[ChatComponent]:
    augmented = list(components or [])
    seen = {_component_type_value(component) for component in augmented}

    text = str(reply_text or "").strip()
    if text and ChatComponentType.ASSISTANT_MESSAGE.value not in seen:
        assistant_component = assistant_message_component(text)
        if assistant_component is not None:
            augmented.insert(0, assistant_component)
            seen.add(ChatComponentType.ASSISTANT_MESSAGE.value)

    product_types = {
        ChatComponentType.PRODUCT_CARDS.value,
        ChatComponentType.PRODUCT_DETAIL.value,
    }
    cards = list(product_carousel or [])
    if cards and not seen.intersection(product_types):
        product_component = product_cards_component(cards)
        if product_component is not None:
            augmented.append(product_component)
            seen.add(ChatComponentType.PRODUCT_CARDS.value)

    return augmented


class ChatResponseMeta(BaseModel):
    query_summary: str = ""
    latency_ms: float = 0.0
    source: Literal["sql", "vector", "tool", "knowledge", "error"] = "error"
    llm_calls: int = 0
    embedding_calls: int = 0
    product_result_count: int = 0
    product_display_count: int = 0
    product_has_more: bool = False


class ChatResponse(BaseModel):
    conversation_id: int
    reply_text: str = Field(
        default="",
        exclude=True,
        json_schema_extra={"deprecated": True, "description": "Legacy compatibility field; use components."},
    )
    carousel_msg: Optional[str] = Field(
        default=None,
        exclude=True,
        json_schema_extra={"deprecated": True, "description": "Legacy compatibility field; use components."},
    )
    product_carousel: List[ProductCard] = Field(
        default_factory=list,
        exclude=True,
        json_schema_extra={"deprecated": True, "description": "Legacy compatibility field; use components."},
    )
    routing: ChatRouting = Field(default_factory=ChatRouting)
    sources: List[KnowledgeSource] = []
    debug: Dict[str, Any] = Field(default_factory=dict)
    view_button_text: str = "View Product Details"
    material_label: str = "Material"
    jewelry_type_label: str = "Jewelry Type"
    components: List[ChatComponent] = Field(default_factory=list)
    meta: Optional[ChatResponseMeta | Dict[str, Any]] = None
    qa_log_id: Optional[str] = None

    @model_validator(mode="after")
    def ensure_component_contract(self) -> "ChatResponse":
        self.components = _augment_chat_components(
            components=list(self.components or []),
            reply_text=self.reply_text,
            product_carousel=list(self.product_carousel or []),
        )
        return self


class ChatFeedbackRequest(BaseModel):
    qa_log_id: uuid.UUID
    feedback: Literal[1, -1]


class ChatFeedbackResponse(BaseModel):
    qa_log_id: uuid.UUID
    feedback: Literal[1, -1]
    saved: bool = True


class ChatHistoryMessage(BaseModel):
    role: str
    content: str
    product_data: Optional[List[Dict[str, Any]]] = Field(default=None, exclude=True)
    components: List[ChatComponent] = Field(default_factory=list)
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def ensure_component_contract(self) -> "ChatHistoryMessage":
        if str(self.role or "").strip().lower() != "assistant":
            return self
        product_cards: List[ProductCard] = []
        for raw in list(self.product_data or []):
            if not isinstance(raw, dict):
                continue
            try:
                product_cards.append(ProductCard.model_validate(raw))
            except Exception:
                continue
        self.components = _augment_chat_components(
            components=list(self.components or []),
            reply_text=self.content,
            product_carousel=product_cards,
        )
        return self


class ChatHistoryResponse(BaseModel):
    conversation_id: int
    messages: List[ChatHistoryMessage] = []


class ActiveConversationResponse(BaseModel):
    conversation_id: Optional[int] = None
