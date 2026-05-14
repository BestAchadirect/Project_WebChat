from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings
from app.services.ai.llm_service import llm_service
from app.services.chat.routing import routing_policy
from app.services.chat.routing import signals as routing_signals
from app.services.chat.text_normalization import normalize_user_text

logger = logging.getLogger(__name__)

CatalogIntent = Literal[
    "catalog_search",
    "product_detail",
    "compare_products",
    "attribute_list",
    "store_overview",
    "knowledge",
    "general_talking",
    "fallback",
]
StrictnessValue = Literal["required", "preferred", "optional"]


class QueryConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: float = Field(default=0.0, ge=0.0, le=1.0)
    constraints: float = Field(default=0.0, ge=0.0, le=1.0)
    searchable: float = Field(default=0.0, ge=0.0, le=1.0)


class QueryHardConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: List[str] = Field(default_factory=list)
    gauge: List[str] = Field(default_factory=list)
    diameter: List[str] = Field(default_factory=list)
    length: List[str] = Field(default_factory=list)
    color: List[str] = Field(default_factory=list)
    threading: List[str] = Field(default_factory=list)
    jewelry_type: List[str] = Field(default_factory=list)
    category: List[str] = Field(default_factory=list)
    price: str | None = None
    stock: str | None = None
    sku: List[str] = Field(default_factory=list)


class CatalogQueryUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: CatalogIntent = "fallback"
    is_searchable_enough: bool = False
    clarification_needed: bool = False
    clarification_reason: str | None = None
    missing_slots: List[str] = Field(default_factory=list)
    product_anchor_required: bool = False
    uses_previous_context: bool = False
    resolved_context_reference: str | None = None
    product_type_terms: List[str] = Field(default_factory=list)
    category_terms: List[str] = Field(default_factory=list)
    hard_constraints: QueryHardConstraints = Field(default_factory=QueryHardConstraints)
    soft_hints: List[str] = Field(default_factory=list)
    semantic_query: str = ""
    strictness: Dict[str, StrictnessValue] = Field(default_factory=dict)
    confidence: QueryConfidence = Field(default_factory=QueryConfidence)

    def to_debug_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class QueryUnderstandingResult:
    understanding: CatalogQueryUnderstanding | None = None
    valid: bool = False
    trusted: bool = False
    llm_call_count: int = 0
    debug: Dict[str, Any] = field(default_factory=dict)


def _query_understanding_model() -> str:
    return str(
        getattr(settings, "CHAT_QUERY_UNDERSTANDING_MODEL", "")
        or getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MODEL", "")
        or getattr(settings, "NLU_MODEL", "gpt-5-mini")
    ).strip()


def _query_understanding_timeout_seconds() -> float:
    try:
        return max(8.0, float(getattr(settings, "CHAT_QUERY_UNDERSTANDING_TIMEOUT_SECONDS", 30.0) or 30.0))
    except Exception:
        return 30.0


def _clean_list(values: Sequence[Any]) -> List[str]:
    clean: List[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        text = normalize_user_text(str(value or ""))
        if not text or text in seen:
            continue
        seen.add(text)
        clean.append(text)
    return clean


def _constraint_has_value(constraints: QueryHardConstraints | Mapping[str, Any]) -> bool:
    data = constraints.model_dump(mode="json") if isinstance(constraints, QueryHardConstraints) else dict(constraints or {})
    for key, raw in data.items():
        if key in {"price", "stock"}:
            if str(raw or "").strip():
                return True
            continue
        if any(str(item or "").strip() for item in list(raw or [])):
            return True
    return False


def _looks_like_context_reference(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    return bool(
        re.search(r"\b(show more|more like this|like this|like these|similar|first one|second one|third one|this one|that one)\b", normalized)
        or normalized in {"show more", "more", "next"}
    )


def _has_measurement_signal(text: str) -> bool:
    normalized = normalize_user_text(text)
    return bool(
        re.search(r"\b\d{1,2}\s*g(?:auge)?\b", normalized)
        or re.search(r"\b\d+(?:\.\d+)?\s*(?:mm|inch|inches|in)\b", normalized)
    )


def compute_searchable_enough(
    *,
    text: str,
    product_type_terms: Sequence[str] | None = None,
    category_terms: Sequence[str] | None = None,
    hard_constraints: QueryHardConstraints | Mapping[str, Any] | None = None,
    soft_hints: Sequence[str] | None = None,
    sku_tokens: Sequence[str] | None = None,
    previous_product_ids: Sequence[str] | None = None,
    previous_attribute_filters: Mapping[str, Any] | None = None,
) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    if list(sku_tokens or []) or routing_policy.extract_sku_tokens(normalized):
        return True
    if _clean_list(product_type_terms) or _clean_list(category_terms):
        return True
    if hard_constraints is not None and _constraint_has_value(hard_constraints):
        return True
    if _has_measurement_signal(normalized):
        return True
    if routing_signals.has_specific_product_hint_signal(normalized):
        return True
    has_previous_context = bool(list(previous_product_ids or []) or dict(previous_attribute_filters or {}))
    if has_previous_context and _looks_like_context_reference(normalized):
        return True
    if has_previous_context and (_clean_list(soft_hints) or _constraint_has_value(hard_constraints or {})):
        return True
    return False


def _system_prompt() -> str:
    return (
        "You are a query understanding layer for a body jewelry wholesale ecommerce chatbot. "
        "Return ONLY strict JSON matching the requested schema. "
        "You may infer intent, product type, customer goal, hard constraints, soft style hints, "
        "searchability, missing slots, and whether the user refers to prior products. "
        "You must not invent product existence, SKU matches, price, stock, exact material, exact size, or availability. "
        "Those facts come only from catalog retrieval. "
        "Allowed intent values: catalog_search, product_detail, compare_products, attribute_list, store_overview, knowledge, general_talking, fallback. "
        "Do not clarify just because a shopping query is broad. A query is searchable if it has a product type, category, known attribute, SKU, "
        "a clear style/use-case hint with category context, or a reference to prior products. "
        "Clarify only when missing information prevents safe retrieval, such as price/stock questions with no product anchor. "
        "Put exact filters in hard_constraints only when the user states or implies a concrete product requirement. "
        "Use soft_hints for style words like cute, gothic, minimal, elegant, luxury, simple, dark, shiny, popular, best seller, trending, or gift. "
        "Use strictness.required for only, must be, I need, has to be, no/not exclusions, under price, exact size/gauge/material/threading, and SKU. "
        "Use strictness.preferred for preferences such as prefer or style hints. "
        "Use product_type_terms for product nouns such as labret, septum, navel ring, nose ring, barbell, plug, or tunnel. "
        "Use semantic_query as a concise grounded search phrase assembled from the user's meaning. "
        "For hard_constraints, use only these keys: material, gauge, diameter, length, color, threading, jewelry_type, category, price, stock, sku. "
        "Do not include unsupported JSON keys."
    )


async def infer_catalog_query_understanding(
    *,
    user_text: str,
    normalized_text: str,
    recent_context: Mapping[str, Any] | None = None,
    previous_product_ids: Sequence[str] | None = None,
    previous_search_plan: Mapping[str, Any] | None = None,
    pagination_state: Mapping[str, Any] | None = None,
    known_catalog_attributes: Sequence[Mapping[str, Any]] | None = None,
    sku_tokens: Sequence[str] | None = None,
) -> QueryUnderstandingResult:
    debug: Dict[str, Any] = {
        "llm_query_understanding_enabled": bool(getattr(settings, "CHAT_QUERY_UNDERSTANDING_V2_ENABLED", False)),
        "llm_query_understanding_used": False,
        "llm_query_understanding_valid": False,
        "llm_query_understanding_trusted": False,
        "llm_query_understanding_error": "",
    }
    if not bool(getattr(settings, "CHAT_QUERY_UNDERSTANDING_V2_ENABLED", False)):
        return QueryUnderstandingResult(debug=debug)

    clean_text = str(user_text or "").strip()
    if not clean_text:
        return QueryUnderstandingResult(debug=debug)

    payload = {
        "user_message": clean_text,
        "normalized_text": str(normalized_text or "").strip(),
        "recent_context": dict(recent_context or {}),
        "previous_product_ids": [str(item) for item in list(previous_product_ids or []) if str(item).strip()],
        "previous_search_plan": dict(previous_search_plan or {}),
        "pagination_state": dict(pagination_state or {}),
        "known_catalog_attributes": list(known_catalog_attributes or []),
        "sku_tokens": list(sku_tokens or []),
        "required_schema": {
            "intent": "catalog_search | product_detail | compare_products | attribute_list | store_overview | knowledge | general_talking | fallback",
            "is_searchable_enough": "boolean",
            "clarification_needed": "boolean",
            "clarification_reason": "string|null",
            "missing_slots": "array<string>",
            "product_anchor_required": "boolean",
            "uses_previous_context": "boolean",
            "resolved_context_reference": "string|null",
            "product_type_terms": "array<string>",
            "category_terms": "array<string>",
            "hard_constraints": {
                "material": "array<string>",
                "gauge": "array<string>",
                "diameter": "array<string>",
                "length": "array<string>",
                "color": "array<string>",
                "threading": "array<string>",
                "jewelry_type": "array<string>",
                "category": "array<string>",
                "price": "string|null",
                "stock": "string|null",
                "sku": "array<string>",
            },
            "soft_hints": "array<string>",
            "semantic_query": "string",
            "strictness": "object with values required|preferred|optional",
            "confidence": {"intent": "0..1", "constraints": "0..1", "searchable": "0..1"},
        },
    }

    try:
        raw = await llm_service.generate_chat_json(
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
            ],
            model=_query_understanding_model(),
            temperature=0.0,
            max_tokens=max(700, int(getattr(settings, "CHAT_QUERY_UNDERSTANDING_MAX_TOKENS", 1000) or 1000)),
            usage_kind="chat_query_understanding",
            reasoning_effort=str(getattr(settings, "CHAT_QUERY_UNDERSTANDING_REASONING_EFFORT", "low") or "low"),
            timeout=_query_understanding_timeout_seconds(),
        )
        debug["llm_query_understanding_used"] = True
        understanding = CatalogQueryUnderstanding.model_validate(raw or {})
    except (ValidationError, ValueError, TypeError) as exc:
        debug["llm_query_understanding_error"] = str(exc)
        return QueryUnderstandingResult(valid=False, llm_call_count=1, debug=debug)
    except Exception as exc:
        debug["llm_query_understanding_error"] = str(exc)
        logger.warning("query understanding failed: %s", exc)
        return QueryUnderstandingResult(valid=False, llm_call_count=0, debug=debug)

    rule_searchable = compute_searchable_enough(
        text=clean_text,
        product_type_terms=understanding.product_type_terms,
        category_terms=understanding.category_terms,
        hard_constraints=understanding.hard_constraints,
        soft_hints=understanding.soft_hints,
        sku_tokens=sku_tokens,
        previous_product_ids=previous_product_ids,
        previous_attribute_filters=dict((recent_context or {}).get("last_attribute_filters") or {}),
    )
    if rule_searchable and not understanding.is_searchable_enough:
        understanding = understanding.model_copy(
            update={
                "is_searchable_enough": True,
                "clarification_needed": False,
                "clarification_reason": None,
                "missing_slots": [],
            }
        )

    min_confidence = float(getattr(settings, "CHAT_QUERY_UNDERSTANDING_MIN_CONFIDENCE", 0.55) or 0.55)
    trusted = bool(
        understanding.confidence.intent >= min_confidence
        and (understanding.confidence.searchable >= min_confidence or rule_searchable)
    )
    debug["llm_query_understanding_valid"] = True
    debug["llm_query_understanding_trusted"] = trusted
    debug["llm_query_understanding"] = understanding.to_debug_dict()
    debug["searchable_enough"] = bool(understanding.is_searchable_enough)
    return QueryUnderstandingResult(
        understanding=understanding,
        valid=True,
        trusted=trusted,
        llm_call_count=1,
        debug=debug,
    )
