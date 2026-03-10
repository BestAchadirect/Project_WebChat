from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.chat import commerce_intents
from app.services.chat.components.types import ComponentSource

_SMALLTALK_TERMS = {
    "hi",
    "hello",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
}

_POLICY_TERMS = {
    "shipping",
    "warranty",
    "refund",
    "return",
    "payment",
    "tax",
    "vat",
    "customs",
    "policy",
    "sample",
    "minimum order",
    "moq",
}

_PRODUCT_TERMS = {
    "sku",
    "ring",
    "barbell",
    "labret",
    "clicker",
    "plug",
    "tunnel",
    "color",
    "material",
    "gauge",
    "threading",
    "compare",
    "table",
    "stock",
    "price",
}


@dataclass(frozen=True)
class RouteDecision:
    intent: str
    source: ComponentSource
    smalltalk_intent: bool
    knowledge_intent: bool
    compare_requested: bool
    recommendation_requested: bool
    store_overview_request: bool


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def is_smalltalk(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    return normalized in _SMALLTALK_TERMS


def is_store_overview_request(
    *,
    text: str,
    detail_has_filters: bool,
    detail_request: bool,
    sku_tokens: Sequence[str],
) -> bool:
    return bool(
        commerce_intents.is_store_overview_request(text)
        and not detail_has_filters
        and not detail_request
        and not sku_tokens
    )


def is_knowledge_intent(
    *,
    text: str,
    detail_has_filters: bool,
    detail_request: bool,
    sku_tokens: Sequence[str],
) -> bool:
    normalized = normalize_text(text)
    if detail_request or detail_has_filters or sku_tokens:
        return False
    if any(term in normalized for term in _POLICY_TERMS):
        return True
    if any(term in normalized for term in _PRODUCT_TERMS):
        return False
    return normalized.endswith("?")


def decide_route(
    *,
    text: str,
    detail_has_filters: bool,
    detail_request: bool,
    sku_tokens: Sequence[str],
) -> RouteDecision:
    compare_requested = commerce_intents.is_compare_request(text)
    recommendation_requested = commerce_intents.is_recommendation_request(text)
    store_overview_requested = is_store_overview_request(
        text=text,
        detail_has_filters=detail_has_filters,
        detail_request=detail_request,
        sku_tokens=sku_tokens,
    )
    smalltalk_intent = is_smalltalk(text)
    knowledge_intent = False
    if not store_overview_requested:
        knowledge_intent = is_knowledge_intent(
            text=text,
            detail_has_filters=detail_has_filters,
            detail_request=detail_request,
            sku_tokens=sku_tokens,
        )

    if smalltalk_intent:
        return RouteDecision(
            intent="smalltalk",
            source=ComponentSource.TOOL,
            smalltalk_intent=True,
            knowledge_intent=False,
            compare_requested=compare_requested,
            recommendation_requested=recommendation_requested,
            store_overview_request=store_overview_requested,
        )

    if knowledge_intent:
        intent = "knowledge_query"
    elif compare_requested:
        intent = "compare_products"
    elif recommendation_requested:
        intent = "recommend_products"
    else:
        intent = "search_specific" if sku_tokens else "browse_products"

    return RouteDecision(
        intent=intent,
        source=ComponentSource.KNOWLEDGE if knowledge_intent else ComponentSource.SQL,
        smalltalk_intent=False,
        knowledge_intent=knowledge_intent,
        compare_requested=compare_requested,
        recommendation_requested=recommendation_requested,
        store_overview_request=store_overview_requested,
    )
