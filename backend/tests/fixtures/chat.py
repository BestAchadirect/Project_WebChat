from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.schemas.chat import (
    ChatComponent,
    ChatResponse,
    ChatResponseMeta,
    ChatRouting,
    KnowledgeSource,
    ProductCard,
)
from app.services.ai.llm_service import llm_service
from app.services.chat.components.pipeline import ComponentPipelineResult
from app.services.chat.service import ChatService


def load_json_dataset(path: str | Path, *, infer_suite: bool = False) -> list[dict[str, Any]]:
    dataset_path = Path(path)
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"dataset must be a list: {dataset_path}")
    cases = [dict(item or {}) for item in payload]
    if infer_suite:
        suite = _infer_suite_from_path(dataset_path)
        for case in cases:
            case.setdefault("suite", suite)
            case.setdefault("dataset_path", str(dataset_path))
    return cases


def _infer_suite_from_path(path: Path) -> str:
    name = path.stem.lower()
    if "logic" in name:
        return "ai_logic"
    if "faq" in name:
        return "faq"
    if "product" in name:
        return "product"
    return "unknown"


class DummyUser:
    id = "user-1"
    customer_name = None
    email = None


class DummyConversation:
    def __init__(self, conversation_id: int = 42, state: Any = None) -> None:
        self.id = conversation_id
        self.state = state


class RedisStub:
    async def get_json(self, key: str) -> None:
        return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int = 0) -> None:
        return None


class KnowledgeStub:
    async def search(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


def build_product_cards(items: list[dict[str, Any]] | None) -> list[ProductCard]:
    cards: list[ProductCard] = []
    for raw in list(items or []):
        item = dict(raw or {})
        cards.append(
            ProductCard(
                id=item.get("id") or uuid4(),
                object_id=str(item.get("object_id") or item.get("sku") or ""),
                sku=str(item.get("sku") or ""),
                legacy_sku=list(item.get("legacy_sku") or []),
                name=str(item.get("name") or item.get("title") or item.get("sku") or "Product"),
                description=item.get("description"),
                price=float(item.get("price", 0.0) or 0.0),
                currency=str(item.get("currency") or "USD"),
                stock_status=item.get("stock_status"),
                image_url=item.get("image_url"),
                product_url=item.get("product_url"),
                attributes=dict(item.get("attributes") or {}),
            )
        )
    return cards


def build_knowledge_sources(items: list[dict[str, Any]] | None) -> list[KnowledgeSource]:
    sources: list[KnowledgeSource] = []
    for index, raw in enumerate(list(items or []), start=1):
        item = dict(raw or {})
        sources.append(
            KnowledgeSource(
                source_id=str(item.get("source_id") or f"source_{index}"),
                chunk_id=item.get("chunk_id"),
                title=str(item.get("title") or "Knowledge"),
                summary=item.get("summary"),
                content_snippet=str(item.get("content_snippet") or item.get("snippet") or ""),
                category=item.get("category"),
                relevance=float(item.get("relevance", 0.8) or 0.8),
                url=item.get("url"),
                distance=item.get("distance"),
            )
        )
    return sources


def patch_llm_tracking(monkeypatch: Any) -> None:
    async def fake_generate_chat_json(**kwargs: Any) -> dict[str, Any]:
        usage_kind = str(kwargs.get("usage_kind") or "")
        messages = list(kwargs.get("messages") or [])
        payload = str(messages[-1].get("content") if messages else "").lower()
        if usage_kind == "chat_interpretation":
            if any(token in payload for token in ("stock", "inventory", "availability")):
                return {
                    "workflow": "catalog",
                    "execution_mode": "agentic",
                    "needs_products": True,
                    "needs_knowledge": False,
                    "needs_clarification": False,
                    "store_overview_request": False,
                    "reason": "stock_lookup",
                    "confidence": 0.9,
                    "requested_fields": [],
                    "attribute_filters": {},
                    "wants_image": False,
                    "semantic_hints": [],
                    "clarify_focus": "",
                }
            if any(token in payload for token in ("policy", "contact", "support")):
                return {
                    "workflow": "knowledge",
                    "execution_mode": "component",
                    "needs_products": False,
                    "needs_knowledge": True,
                    "needs_clarification": False,
                    "store_overview_request": False,
                    "knowledge_query": "store policy request",
                    "reason": "knowledge_request",
                    "confidence": 0.8,
                    "requested_fields": [],
                    "attribute_filters": {},
                    "wants_image": False,
                    "semantic_hints": [],
                    "clarify_focus": "",
                }
            return {
                "workflow": "catalog",
                "execution_mode": "agentic",
                "needs_products": True,
                "needs_knowledge": False,
                "needs_clarification": False,
                "store_overview_request": False,
                "reason": "default_component",
                "confidence": 0.6,
                "requested_fields": [],
                "attribute_filters": {},
                "wants_image": False,
                "semantic_hints": [],
                "clarify_focus": "",
            }
        if usage_kind != "routing_decision":
            return {}
        if any(token in payload for token in ("stock", "inventory", "availability")):
            return {
                "workflow": "catalog",
                "execution_mode": "agentic",
                "needs_products": True,
                "needs_knowledge": False,
                "needs_clarification": False,
                "store_overview_request": False,
                "reason": "stock_lookup",
                "confidence": 0.9,
            }
        if any(token in payload for token in ("policy", "contact", "support")):
            return {
                "workflow": "knowledge",
                "execution_mode": "component",
                "needs_products": False,
                "needs_knowledge": True,
                "needs_clarification": False,
                "store_overview_request": False,
                "reason": "knowledge_request",
                "confidence": 0.8,
            }
        return {
            "workflow": "catalog",
            "execution_mode": "component",
            "needs_products": True,
            "needs_knowledge": False,
            "needs_clarification": False,
            "store_overview_request": False,
            "reason": "default_component",
            "confidence": 0.6,
        }

    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)


def patch_chat_service_lifecycle(
    monkeypatch: Any,
    *,
    conversation: DummyConversation | None = None,
    finalize_response: Callable[..., Awaitable[Any]] | None = None,
) -> None:
    async def fake_get_or_create_user(self, user_id: str, name: str | None = None, email: str | None = None):
        return DummyUser()

    async def fake_get_or_create_conversation(self, user: DummyUser, conversation_id: int | None):
        return conversation or DummyConversation()

    async def default_finalize_response(self, *, response: ChatResponse, **kwargs: Any) -> ChatResponse:
        return response

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(
        ChatService,
        "_finalize_response",
        finalize_response or default_finalize_response,
    )
    patch_llm_tracking(monkeypatch)


def build_component_pipeline_result(
    *,
    request: Any,
    conversation_id: int,
    reply_text: str,
    component_text: str | None = None,
    response_workflow: str = "catalog",
    source: str = "sql",
    debug: dict[str, Any] | None = None,
    response_debug: dict[str, Any] | None = None,
    conversation_state: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    product_carousel: list[dict[str, Any]] | None = None,
    components: list[dict[str, Any] | ChatComponent] | None = None,
) -> ComponentPipelineResult:
    pipeline_debug = {
        "component_plan": ["query_summary"],
        "component_source": source,
    }
    if debug:
        pipeline_debug.update(debug)

    response_components = [
        component if isinstance(component, ChatComponent) else ChatComponent.model_validate(component)
        for component in list(components or [])
    ]
    if not response_components:
        response_components = [ChatComponent(type="query_summary", data={"text": component_text or reply_text})]
    response_sources = build_knowledge_sources(sources)
    response_products = build_product_cards(product_carousel)

    return ComponentPipelineResult(
        response=ChatResponse(
            conversation_id=conversation_id,
            reply_text=reply_text,
            carousel_msg="",
            product_carousel=response_products,
            routing=ChatRouting(
                workflow=response_workflow,
                execution_mode="component",
                needs_products=response_workflow == "catalog",
                needs_knowledge=response_workflow == "knowledge",
                needs_clarification=response_workflow == "fallback",
                reason="fixture",
                selection_source="fixture",
            ),
            sources=response_sources,
            debug=response_debug or {},
            components=response_components,
            meta=ChatResponseMeta(
                query_summary=request.message,
                latency_ms=1.0,
                source=source,
                llm_calls=0,
                embedding_calls=0,
                product_result_count=len(response_products),
                product_display_count=len(response_products),
                product_has_more=False,
            ),
        ),
        detail_mode_triggered=False,
        llm_calls=0,
        embedding_calls=0,
        external_call_counts={},
        spans={"response_build_ms": 1.0},
        debug=pipeline_debug,
        conversation_state=conversation_state,
    )
