from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.chat.routing import routing_policy
from app.services.chat.runtime import context_policy, conversation_state
from app.services.chat.text_normalization import normalize_user_text

CONTEXT_USE_THRESHOLD = 0.80
CONTEXT_CLARIFY_THRESHOLD = 0.50

_PRICE_COMPARE_TERMS = (
    "cheapest",
    "cheaper",
    "lower price",
    "lowest price",
    "less expensive",
    "budget option",
    "budget",
)
_RELATED_PRODUCT_TERMS = (
    "similar product",
    "similar products",
    "related product",
    "related products",
    "like this",
    "like these",
    "same style",
    "another option",
    "other option",
)
_COMPARE_TERMS = ("compare", "versus", "vs")
_STRICT_FOLLOWUP_TERMS = ("only", "must", "has to", "need", "under")
_DESCRIPTOR_FILTER_KEYS = {"material", "color", "gauge", "length", "threading"}


@dataclass(frozen=True)
class ContextResolution:
    context_type: str = "none"
    uses_previous_context: bool = False
    confidence: float = 0.0
    reason: str = ""
    merged_query: str = ""
    merged_attribute_filters: Dict[str, str] = field(default_factory=dict)
    resolved_product_anchor_ids: List[str] = field(default_factory=list)
    resolved_product_anchor_skus: List[str] = field(default_factory=list)
    selected_product_index: Optional[int] = None
    selected_product_indices: List[int] = field(default_factory=list)
    resume_pending_task: bool = False
    pending_task_type: Optional[str] = None
    pagination_action: Optional[Dict[str, Any]] = None
    bypass_missing_anchor_clarify: bool = False
    should_clarify: bool = False
    clarification_reason: Optional[str] = None
    safe_to_retrieve: bool = False
    debug: Dict[str, Any] = field(default_factory=dict)
    context_action: str = "ignore"
    resolved_intent: str = "unknown"
    active_product: Optional[Dict[str, Any]] = None
    referenced_products: List[Dict[str, Any]] = field(default_factory=list)
    pending_task_action: Optional[Dict[str, Any]] = None
    reset_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.resume_pending_task and self.pending_task_action is None:
            object.__setattr__(self, "pending_task_action", {"action": "resume", "clear": True})
        if self.selected_product_index is None and self.selected_product_indices:
            object.__setattr__(self, "selected_product_index", int(self.selected_product_indices[0]))

    @property
    def context_used(self) -> bool:
        return bool(self.uses_previous_context)

    @property
    def resolved_filters(self) -> Dict[str, str]:
        return dict(self.merged_attribute_filters or {})

    def to_debug_dict(self) -> Dict[str, Any]:
        return {
            "context_type": self.context_type,
            "uses_previous_context": bool(self.uses_previous_context),
            "context_used": bool(self.uses_previous_context),
            "context_action": self.context_action,
            "resolved_intent": self.resolved_intent,
            "confidence": float(self.confidence or 0.0),
            "reason": self.reason,
            "merged_query": self.merged_query,
            "merged_attribute_filters": dict(self.merged_attribute_filters or {}),
            "resolved_filters": dict(self.merged_attribute_filters or {}),
            "resolved_product_anchor_ids": list(self.resolved_product_anchor_ids or []),
            "resolved_product_anchor_skus": list(self.resolved_product_anchor_skus or []),
            "selected_product_index": self.selected_product_index,
            "selected_product_indices": list(self.selected_product_indices or []),
            "resume_pending_task": bool(self.resume_pending_task),
            "pending_task_type": str(self.pending_task_type or ""),
            "pagination_action": dict(self.pagination_action or {}) if self.pagination_action else None,
            "bypass_missing_anchor_clarify": bool(self.bypass_missing_anchor_clarify),
            "should_clarify": bool(self.should_clarify),
            "clarification_reason": self.clarification_reason,
            "safe_to_retrieve": bool(self.safe_to_retrieve),
            "active_product": dict(self.active_product or {}),
            "referenced_products": [dict(item) for item in list(self.referenced_products or [])],
            "pending_task_action": dict(self.pending_task_action or {}) if self.pending_task_action else None,
            "reset_reason": self.reset_reason,
            "debug": dict(self.debug or {}),
        }


def _clean_filter_map(value: Mapping[str, Any] | None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, raw in dict(value or {}).items():
        clean_key = str(key or "").strip().lower()
        clean_value = str(raw or "").strip()
        if clean_key and clean_value:
            out[clean_key] = clean_value
    return out


def _merge_filters(*, previous: Dict[str, str], current: Dict[str, str]) -> Dict[str, str]:
    merged = dict(previous or {})
    for key, value in dict(current or {}).items():
        clean_key = str(key or "").strip().lower()
        clean_value = str(value or "").strip()
        if not clean_key or not clean_value:
            continue
        merged[clean_key] = clean_value
    return merged


def _active_from_displayed(item: Mapping[str, Any], *, source: str, confidence: float, now: Optional[datetime]) -> Dict[str, Any]:
    timestamp = context_policy.utc_timestamp(now)
    return {
        "product_id": str(item.get("product_id") or "").strip(),
        "sku": str(item.get("sku") or "").strip(),
        "master_code": str(item.get("master_code") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "source": source,
        "confidence": float(confidence),
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _active_from_sku(sku: str, *, now: Optional[datetime]) -> Dict[str, Any]:
    timestamp = context_policy.utc_timestamp(now)
    clean_sku = str(sku or "").strip()
    return {
        "product_id": "",
        "sku": clean_sku,
        "master_code": clean_sku,
        "name": "",
        "source": "explicit_sku",
        "confidence": 0.95,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _summary_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "last_attribute_filters": dict(state.get("last_attribute_filters") or {}),
        "last_product_count": len(list(state.get("last_product_ids") or [])),
        "displayed_product_count": len(list(state.get("displayed_products") or [])),
        "has_active_product": bool(dict(state.get("active_product") or {})),
        "has_pending_task": bool(dict(state.get("pending_task") or {})),
        "last_route": str(state.get("last_route") or ""),
        "last_query_cache_key": str(state.get("last_query_cache_key") or ""),
    }


def _resolved_intent_from_detail(text: str, workflow: str, requested_fields: Sequence[str]) -> str:
    workflow_norm = str(workflow or "").strip().lower()
    fields = set(context_policy.detail_fields_from_text(text))
    fields.update(str(item or "").strip().lower() for item in list(requested_fields or []) if str(item or "").strip())
    if "stock" in fields:
        return "inventory_check"
    if fields.intersection({"price", "attributes", "image"}):
        return "product_detail"
    if workflow_norm == "knowledge":
        return "knowledge_question"
    if workflow_norm == "catalog":
        return "product_search"
    return "unknown"


def _pending_task_type_from(value: Any) -> str:
    return str(
        getattr(value, "pending_task_type", "")
        or (value.get("pending_task_type") if isinstance(value, dict) else "")
        or ""
    ).strip().lower()


def _missing_slot_from(value: Any) -> str:
    return str(
        getattr(value, "missing_slot", "")
        or (value.get("missing_slot") if isinstance(value, dict) else "")
        or ""
    ).strip().lower()


def _response_policy_from(value: Any) -> str:
    return str(
        getattr(value, "response_policy", "")
        or (value.get("response_policy") if isinstance(value, dict) else "")
        or ""
    ).strip().lower()


def _fallback_displayed_products(*, product_ids: Sequence[str], product_skus: Sequence[str]) -> List[Dict[str, Any]]:
    fallback: List[Dict[str, Any]] = []
    clean_ids = [str(item or "").strip() for item in list(product_ids or []) if str(item or "").strip()]
    clean_skus = [str(item or "").strip() for item in list(product_skus or []) if str(item or "").strip()]
    total = max(len(clean_ids), len(clean_skus))
    for index in range(total):
        fallback.append(
            {
                "position": index + 1,
                "product_id": clean_ids[index] if index < len(clean_ids) else "",
                "sku": clean_skus[index] if index < len(clean_skus) else "",
                "master_code": clean_skus[index] if index < len(clean_skus) else "",
                "name": "",
                "descriptors": {},
            }
        )
    return fallback


def _normalize_displayed_products(
    *,
    displayed_products: Sequence[Mapping[str, Any]],
    previous_product_ids: Sequence[str],
    previous_product_skus: Sequence[str],
) -> List[Dict[str, Any]]:
    clean_displayed = [dict(item) for item in list(displayed_products or []) if isinstance(item, Mapping)]
    if clean_displayed:
        return clean_displayed
    return _fallback_displayed_products(
        product_ids=previous_product_ids,
        product_skus=previous_product_skus,
    )


def _build_merged_query(filters: Mapping[str, Any], *, fallback_query: str = "") -> str:
    order = ("color", "material", "threading", "gauge", "length", "jewelry_type", "category")
    parts: List[str] = []
    seen: set[str] = set()
    for key in order:
        text = str(dict(filters or {}).get(key) or "").strip()
        if not text:
            continue
        normalized = normalize_user_text(text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        parts.append(text)
    query = " ".join(parts).strip()
    if query:
        return query
    return str(fallback_query or "").strip()


def _looks_like_price_compare(*, text: str, semantic_hints: Sequence[str], decision_state: Any, pending_task_type: str) -> bool:
    if pending_task_type in {"compare_price", "find_cheaper_products"}:
        return True
    if _pending_task_type_from(decision_state) in {"compare_price", "find_cheaper_products"} and _missing_slot_from(decision_state) == "product_anchor":
        return True
    normalized = normalize_user_text(text)
    if any(term in normalized for term in _PRICE_COMPARE_TERMS):
        return True
    hints = {
        str(item or "").strip().lower()
        for item in list(semantic_hints or [])
        if str(item or "").strip()
    }
    return bool(hints.intersection({"cheapest", "lower price", "cheaper", "lowest price", "budget"}))


def _looks_like_related_products(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    return any(term in normalized for term in _RELATED_PRODUCT_TERMS)


def _looks_like_compare_request(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    return any(term in normalized for term in _COMPARE_TERMS)


def _has_strict_followup_marker(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    if any(term in normalized for term in _STRICT_FOLLOWUP_TERMS):
        return True
    return bool(re.search(r"\b(?:no|not)\b", normalized))


def _extract_selected_indices(text: str, *, displayed_count: int) -> List[int]:
    normalized = normalize_user_text(text)
    if not normalized or displayed_count <= 0:
        return []

    positions: List[int] = []
    for match in re.finditer(r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last)\b", normalized):
        token = str(match.group(1) or "").strip().lower()
        if token == "last":
            position = displayed_count
        else:
            position = int(context_policy.ORDINALS.get(token, 0) or 0)
        if 1 <= position <= displayed_count and position not in positions:
            positions.append(position)
    for match in re.finditer(r"(?:#|number\s+)(\d{1,2})", normalized):
        try:
            position = int(match.group(1) or 0)
        except Exception:
            position = 0
        if 1 <= position <= displayed_count and position not in positions:
            positions.append(position)
    return [position - 1 for position in positions]


def _product_from_index(displayed_products: Sequence[Mapping[str, Any]], index: int) -> Dict[str, Any]:
    target_position = int(index) + 1
    for item in list(displayed_products or []):
        try:
            item_position = int(item.get("position") or 0)
        except Exception:
            item_position = 0
        if item_position == target_position:
            return dict(item)
    return {}


def _products_from_indices(displayed_products: Sequence[Mapping[str, Any]], indices: Sequence[int]) -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index in list(indices or []):
        product = _product_from_index(displayed_products, int(index))
        if not product:
            continue
        key = (
            str(product.get("product_id") or "").strip(),
            str(product.get("sku") or "").strip().lower(),
            str(product.get("master_code") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        products.append(product)
    return products


def _displayed_descriptors(item: Mapping[str, Any]) -> Dict[str, str]:
    return _clean_filter_map(item.get("descriptors"))


def _value_matches_descriptor(*, expected: str, actual: str) -> bool:
    expected_norm = normalize_user_text(expected)
    actual_norm = normalize_user_text(actual)
    if not expected_norm or not actual_norm:
        return False
    return (
        expected_norm == actual_norm
        or expected_norm in actual_norm
        or actual_norm in expected_norm
    )


def _descriptor_candidates(
    *,
    displayed_products: Sequence[Mapping[str, Any]],
    normalized_text: str,
    current_filters: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    filter_candidates = {
        key: value
        for key, value in dict(current_filters or {}).items()
        if key in _DESCRIPTOR_FILTER_KEYS and str(value or "").strip()
    }
    if filter_candidates:
        for item in list(displayed_products or []):
            descriptors = _displayed_descriptors(item)
            if descriptors and all(
                _value_matches_descriptor(expected=str(value), actual=str(descriptors.get(key) or ""))
                for key, value in filter_candidates.items()
            ):
                candidates.append(dict(item))
                continue
            haystack = normalize_user_text(
                " ".join(
                    [
                        str(item.get("sku") or ""),
                        str(item.get("master_code") or ""),
                        str(item.get("name") or ""),
                        " ".join(str(raw or "") for raw in descriptors.values()),
                    ]
                )
            )
            if haystack and all(normalize_user_text(str(value or "")) in haystack for value in filter_candidates.values()):
                candidates.append(dict(item))
        return candidates

    token_matches: List[Dict[str, Any]] = []
    tokens = [token for token in normalized_text.split() if len(token) >= 4]
    for item in list(displayed_products or []):
        haystack = normalize_user_text(
            " ".join(
                [
                    str(item.get("sku") or ""),
                    str(item.get("master_code") or ""),
                    str(item.get("name") or ""),
                ]
            )
        )
        if haystack and any(token in haystack for token in tokens):
            token_matches.append(dict(item))
    return token_matches


def _anchor_ids_from_products(products: Sequence[Mapping[str, Any]]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in list(products or []):
        product_id = str(item.get("product_id") or "").strip()
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        out.append(product_id)
    return out


def _anchor_skus_from_products(products: Sequence[Mapping[str, Any]]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in list(products or []):
        for raw in (item.get("sku"), item.get("master_code")):
            sku = str(raw or "").strip()
            key = sku.lower()
            if not sku or key in seen:
                continue
            seen.add(key)
            out.append(sku)
    return out


def resolve_context(
    *,
    user_message: str,
    conversation_id: Any,
    loaded_state: Any,
    workflow: str = "",
    extracted_filters: Mapping[str, Any] | None = None,
    requested_fields: Sequence[str] | None = None,
    semantic_hints: Sequence[str] | None = None,
    is_detail_request: bool = False,
    sku_tokens: Sequence[str] | None = None,
    client_action: str = "",
    client_action_payload: Mapping[str, Any] | None = None,
    decision_state: Any = None,
    normalized_text: str = "",
    now: Optional[datetime] = None,
) -> ContextResolution:
    state = conversation_state.load_state(loaded_state)
    normalized = str(normalized_text or normalize_user_text(user_message) or "").strip()
    previous_filters = _clean_filter_map(state.get("last_attribute_filters"))
    extracted_clean = _clean_filter_map(extracted_filters)
    text_filter_overrides = context_policy.extract_filter_overrides(user_message)
    if previous_filters and not context_policy.has_explicit_product_type_signal(user_message):
        extracted_clean.pop("jewelry_type", None)
        extracted_clean.pop("category", None)
    current_filters = _merge_filters(previous=extracted_clean, current=text_filter_overrides)

    previous_product_ids = [
        str(item or "").strip()
        for item in list(state.get("last_product_ids") or [])
        if str(item or "").strip()
    ]
    previous_product_skus = [
        str(item or "").strip()
        for item in list(state.get("last_product_skus") or [])
        if str(item or "").strip()
    ]
    displayed_products = _normalize_displayed_products(
        displayed_products=list(state.get("displayed_products") or []),
        previous_product_ids=previous_product_ids,
        previous_product_skus=previous_product_skus,
    )
    active_product = dict(state.get("active_product") or {})
    pending_task = dict(state.get("pending_task") or {})
    clarification = dict(state.get("clarification_state") or {})
    pending_task_type = str(pending_task.get("task_type") or "").strip().lower()
    pending_missing_slot = str(pending_task.get("missing_slot") or "").strip().lower()
    sku_list = [
        str(item or "").strip()
        for item in list(sku_tokens or routing_policy.extract_sku_tokens(user_message))
        if str(item or "").strip()
    ]
    requested = [
        str(item or "").strip().lower()
        for item in list(requested_fields or [])
        if str(item or "").strip()
    ]
    semantic_hints_clean = [
        str(item or "").strip().lower()
        for item in list(semantic_hints or [])
        if str(item or "").strip()
    ]
    detail_intent = _resolved_intent_from_detail(user_message, workflow, requested)
    sensitive_detail = bool(is_detail_request) or context_policy.is_product_sensitive_detail(user_message, list(requested))
    pronoun_reference = context_policy.has_pronoun_product_reference(user_message)
    active_is_valid = bool(active_product) and not context_policy.active_product_expired(active_product, now=now)
    selected_indices = _extract_selected_indices(user_message, displayed_count=len(displayed_products))
    selected_products = _products_from_indices(displayed_products, selected_indices)
    descriptor_candidates = _descriptor_candidates(
        displayed_products=displayed_products,
        normalized_text=normalized,
        current_filters=current_filters,
    )
    compare_requested = _looks_like_compare_request(user_message)
    price_compare_requested = _looks_like_price_compare(
        text=user_message,
        semantic_hints=semantic_hints_clean,
        decision_state=decision_state,
        pending_task_type=pending_task_type,
    )
    related_requested = _looks_like_related_products(user_message)

    debug = {
        "conversation_id": str(conversation_id or ""),
        "user_message": str(user_message or "")[:500],
        "normalized_text": normalized,
        "previous_context_summary": _summary_from_state(state),
        "current_filters": dict(current_filters),
        "sku_tokens": list(sku_list),
        "selected_product_indices": list(selected_indices),
        "descriptor_candidate_count": len(descriptor_candidates),
        "clarification_state": {
            "last_reason": str(clarification.get("last_clarification_reason") or ""),
            "last_context_type": str(clarification.get("last_context_type") or ""),
            "last_missing_slot": str(clarification.get("last_missing_slot") or ""),
            "answered_missing_slot": bool(clarification.get("answered_missing_slot")),
        },
        "previous_filters_used": False,
        "previous_products_used": False,
        "pending_task_used": False,
        "pagination_state_used": False,
        "strict_followup": _has_strict_followup_marker(user_message),
    }

    client_action_norm = str(client_action or "").strip().lower()
    client_payload = dict(client_action_payload or {})
    if client_action_norm in {"catalog_pagination", "show_more"} or context_policy.detects_pagination(user_message):
        query_ids = [
            str(item or "").strip()
            for item in list(client_payload.get("query_product_ids") or state.get("last_query_product_ids") or [])
            if str(item or "").strip()
        ]
        query_key = str(client_payload.get("query_cache_key") or state.get("last_query_cache_key") or "").strip()
        state_offset = int(state.get("last_display_offset") or 0)
        payload_offset_raw = client_payload.get("display_offset")
        try:
            payload_offset = int(payload_offset_raw) if payload_offset_raw is not None else None
        except Exception:
            payload_offset = None
        display_offset = int(payload_offset if payload_offset is not None else state_offset)
        display_limit = int(client_payload.get("display_limit") or state.get("last_display_limit") or 0)
        result_count = int(state.get("last_result_count") or 0)
        action = {
            "query_cache_key": query_key,
            "query_product_ids": query_ids,
            "display_offset": display_offset,
            "display_limit": display_limit,
            "result_count": result_count,
            "state_offset": state_offset,
        }
        debug["pagination_state_used"] = bool(query_ids or query_key)
        if payload_offset is not None and payload_offset < state_offset:
            return ContextResolution(
                context_type="pagination",
                uses_previous_context=False,
                confidence=0.25,
                reason="Pagination request is stale",
                merged_attribute_filters=dict(previous_filters),
                pagination_action=action,
                bypass_missing_anchor_clarify=False,
                should_clarify=True,
                clarification_reason="pagination_stale",
                safe_to_retrieve=False,
                debug=debug,
                context_action="clarify",
                resolved_intent="pagination",
            )
        if query_ids or query_key:
            return ContextResolution(
                context_type="pagination",
                uses_previous_context=True,
                confidence=0.92,
                reason="Pagination follow-up reused previous result set",
                merged_attribute_filters=dict(previous_filters),
                pagination_action=action,
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent="pagination",
            )
        return ContextResolution(
            context_type="pagination",
            uses_previous_context=False,
            confidence=0.35,
            reason="Pagination requested without reusable result state",
            merged_attribute_filters=dict(previous_filters),
            pagination_action=action,
            bypass_missing_anchor_clarify=False,
            should_clarify=True,
            clarification_reason="pagination_unavailable",
            safe_to_retrieve=False,
            debug=debug,
            context_action="clarify",
            resolved_intent="pagination",
        )

    if pending_task and pending_missing_slot == "product_anchor":
        debug["pending_task_used"] = True
        if len(sku_list) >= 1:
            sku_active = _active_from_sku(sku_list[0], now=now)
            return ContextResolution(
                context_type="pending_task_resume",
                uses_previous_context=True,
                confidence=0.95,
                reason="Pending product-anchor clarification answered with explicit SKU",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_skus=[sku_list[0]],
                resume_pending_task=True,
                pending_task_type=pending_task_type or _pending_task_type_from(decision_state),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent="clarification_response",
                active_product=sku_active,
                referenced_products=[],
            )
        if len(selected_products) == 1:
            resolved_active = _active_from_displayed(
                selected_products[0],
                source="position_reference",
                confidence=0.9,
                now=now,
            )
            debug["previous_products_used"] = True
            return ContextResolution(
                context_type="pending_task_resume",
                uses_previous_context=True,
                confidence=0.9,
                reason="Pending product-anchor clarification answered with product index reference",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_ids=_anchor_ids_from_products(selected_products),
                resolved_product_anchor_skus=_anchor_skus_from_products(selected_products),
                selected_product_indices=list(selected_indices),
                resume_pending_task=True,
                pending_task_type=pending_task_type or _pending_task_type_from(decision_state),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent="clarification_response",
                active_product=resolved_active,
                referenced_products=[dict(selected_products[0])],
            )
        if len(descriptor_candidates) == 1:
            resolved_active = _active_from_displayed(
                descriptor_candidates[0],
                source="inferred_followup",
                confidence=0.85,
                now=now,
            )
            debug["previous_products_used"] = True
            return ContextResolution(
                context_type="pending_task_resume",
                uses_previous_context=True,
                confidence=0.85,
                reason="Pending product-anchor clarification answered with descriptor reference",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_ids=_anchor_ids_from_products(descriptor_candidates),
                resolved_product_anchor_skus=_anchor_skus_from_products(descriptor_candidates),
                resume_pending_task=True,
                pending_task_type=pending_task_type or _pending_task_type_from(decision_state),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent="clarification_response",
                active_product=resolved_active,
                referenced_products=[dict(descriptor_candidates[0])],
            )
        if pronoun_reference and active_is_valid:
            return ContextResolution(
                context_type="pending_task_resume",
                uses_previous_context=True,
                confidence=0.85,
                reason="Pending product-anchor clarification answered with active product reference",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_ids=[str(active_product.get("product_id") or "").strip()] if str(active_product.get("product_id") or "").strip() else [],
                resolved_product_anchor_skus=[
                    str(active_product.get("sku") or active_product.get("master_code") or "").strip()
                ] if str(active_product.get("sku") or active_product.get("master_code") or "").strip() else [],
                resume_pending_task=True,
                pending_task_type=pending_task_type or _pending_task_type_from(decision_state),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent="clarification_response",
                active_product=dict(active_product),
                referenced_products=[dict(active_product)],
            )
        if current_filters or context_policy.has_explicit_product_type_signal(user_message):
            return ContextResolution(
                context_type="pending_task_resume",
                uses_previous_context=False,
                confidence=0.78,
                reason="Pending product-anchor clarification answered with a searchable product anchor",
                merged_query=_build_merged_query(current_filters, fallback_query=user_message),
                merged_attribute_filters=dict(current_filters),
                resume_pending_task=True,
                pending_task_type=pending_task_type or _pending_task_type_from(decision_state),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="update" if current_filters else "reuse",
                resolved_intent="clarification_response",
            )

    if not (compare_requested and len(sku_list) >= 2) and sku_list:
        sku_active = _active_from_sku(sku_list[0], now=now)
        debug["resolved_context"] = {"active_product": sku_active}
        return ContextResolution(
            context_type="explicit_sku",
            uses_previous_context=False,
            confidence=0.95,
            reason="Explicit SKU or master-code reference",
            merged_attribute_filters=dict(current_filters),
            merged_query=str(sku_list[0]),
            resolved_product_anchor_skus=[sku_list[0]],
            bypass_missing_anchor_clarify=True,
            should_clarify=False,
            clarification_reason=None,
            safe_to_retrieve=True,
            debug=debug,
            context_action="reset",
            resolved_intent="product_detail",
            active_product=sku_active,
            referenced_products=[sku_active],
            reset_reason="explicit_sku",
        )

    reset_reason = context_policy.topic_switch_reason(
        text=user_message,
        previous_filters=previous_filters,
        current_filters=current_filters,
    )
    if reset_reason:
        return ContextResolution(
            context_type="topic_reset",
            uses_previous_context=False,
            confidence=0.88 if current_filters else 0.7,
            reason="Topic switch reset",
            merged_query=_build_merged_query(current_filters, fallback_query=user_message),
            merged_attribute_filters=dict(current_filters),
            bypass_missing_anchor_clarify=False,
            should_clarify=False,
            clarification_reason=None,
            safe_to_retrieve=bool(current_filters),
            debug=debug,
            context_action="reset",
            resolved_intent="product_search" if current_filters else "unknown",
            reset_reason=reset_reason,
        )

    if compare_requested and len(selected_products) >= 2:
        debug["previous_products_used"] = True
        return ContextResolution(
            context_type="compare_reference",
            uses_previous_context=True,
            confidence=0.9,
            reason="Compare request resolved from previously displayed products",
            merged_attribute_filters=dict(previous_filters),
            resolved_product_anchor_ids=_anchor_ids_from_products(selected_products),
            resolved_product_anchor_skus=_anchor_skus_from_products(selected_products),
            selected_product_indices=list(selected_indices),
            bypass_missing_anchor_clarify=True,
            should_clarify=False,
            clarification_reason=None,
            safe_to_retrieve=True,
            debug=debug,
            context_action="reuse",
            resolved_intent="compare_products",
            referenced_products=[dict(item) for item in selected_products],
        )
    if compare_requested and displayed_products and not sku_list:
        return ContextResolution(
            context_type="compare_reference",
            uses_previous_context=False,
            confidence=0.35,
            reason="Compare request is missing enough product references",
            merged_attribute_filters=dict(previous_filters),
            selected_product_indices=list(selected_indices),
            bypass_missing_anchor_clarify=False,
            should_clarify=True,
            clarification_reason="product_anchor_ambiguous",
            safe_to_retrieve=False,
            debug=debug,
            context_action="clarify",
            resolved_intent="compare_products",
        )

    if compare_requested and len(sku_list) >= 2:
        return ContextResolution(
            context_type="none",
            uses_previous_context=False,
            confidence=0.0,
            reason="Explicit compare request should be handled by the compare workflow",
            merged_attribute_filters=dict(current_filters),
            bypass_missing_anchor_clarify=False,
            should_clarify=False,
            clarification_reason=None,
            safe_to_retrieve=False,
            debug=debug,
            context_action="ignore",
            resolved_intent="compare_products",
        )

    if price_compare_requested and not current_filters:
        compare_products = displayed_products or _fallback_displayed_products(
            product_ids=previous_product_ids,
            product_skus=previous_product_skus,
        )
        if compare_products:
            debug["previous_products_used"] = True
            return ContextResolution(
                context_type="price_compare",
                uses_previous_context=True,
                confidence=0.88,
                reason="Price comparison follow-up reused previous products",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_ids=_anchor_ids_from_products(compare_products),
                resolved_product_anchor_skus=_anchor_skus_from_products(compare_products),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent="compare_products",
                referenced_products=[dict(item) for item in compare_products],
            )
        if pending_task_type in {"compare_price", "find_cheaper_products"} or _pending_task_type_from(decision_state) in {"compare_price", "find_cheaper_products"}:
            return ContextResolution(
                context_type="price_compare",
                uses_previous_context=False,
                confidence=0.35,
                reason="Price comparison needs prior products or a product anchor",
                merged_attribute_filters=dict(previous_filters),
                bypass_missing_anchor_clarify=False,
                should_clarify=True,
                clarification_reason="product_anchor_missing",
                safe_to_retrieve=False,
                debug=debug,
                context_action="clarify",
                resolved_intent="compare_products",
            )

    if related_requested and not current_filters:
        related_products = displayed_products or _fallback_displayed_products(
            product_ids=previous_product_ids,
            product_skus=previous_product_skus,
        )
        if related_products:
            debug["previous_products_used"] = True
            return ContextResolution(
                context_type="related_products",
                uses_previous_context=True,
                confidence=0.88,
                reason="Related-products follow-up reused previous products",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_ids=_anchor_ids_from_products(related_products),
                resolved_product_anchor_skus=_anchor_skus_from_products(related_products),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent="product_search",
                referenced_products=[dict(item) for item in related_products],
            )
        return ContextResolution(
            context_type="related_products",
            uses_previous_context=False,
            confidence=0.35,
            reason="Related-products follow-up needs a previous product anchor",
            merged_attribute_filters=dict(previous_filters),
            bypass_missing_anchor_clarify=False,
            should_clarify=True,
            clarification_reason="product_anchor_missing",
            safe_to_retrieve=False,
            debug=debug,
            context_action="clarify",
            resolved_intent="product_search",
        )

    if sensitive_detail or pronoun_reference or len(selected_products) == 1:
        if len(selected_products) == 1:
            resolved_active = _active_from_displayed(
                selected_products[0],
                source="position_reference",
                confidence=0.9,
                now=now,
            )
            debug["previous_products_used"] = True
            return ContextResolution(
                context_type="detail_reference",
                uses_previous_context=True,
                confidence=0.9,
                reason="Product index reference resolved from displayed products",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_ids=_anchor_ids_from_products(selected_products),
                resolved_product_anchor_skus=_anchor_skus_from_products(selected_products),
                selected_product_indices=list(selected_indices),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
                active_product=resolved_active,
                referenced_products=[dict(selected_products[0])],
            )
        if current_filters:
            return ContextResolution(
                context_type="detail_reference",
                uses_previous_context=False,
                confidence=0.72,
                reason="Searchable detail request can be resolved from explicit filters",
                merged_query=_build_merged_query(current_filters, fallback_query=user_message),
                merged_attribute_filters=dict(current_filters),
                bypass_missing_anchor_clarify=False,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="update",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
            )
        if len(descriptor_candidates) == 1:
            resolved_active = _active_from_displayed(
                descriptor_candidates[0],
                source="inferred_followup",
                confidence=0.85,
                now=now,
            )
            debug["previous_products_used"] = True
            return ContextResolution(
                context_type="detail_reference",
                uses_previous_context=True,
                confidence=0.85,
                reason="Descriptor reference resolved from displayed products",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_ids=_anchor_ids_from_products(descriptor_candidates),
                resolved_product_anchor_skus=_anchor_skus_from_products(descriptor_candidates),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
                active_product=resolved_active,
                referenced_products=[dict(descriptor_candidates[0])],
            )
        if active_is_valid:
            return ContextResolution(
                context_type="detail_reference",
                uses_previous_context=True,
                confidence=0.85,
                reason="Single active product follow-up",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_ids=[str(active_product.get("product_id") or "").strip()] if str(active_product.get("product_id") or "").strip() else [],
                resolved_product_anchor_skus=[
                    str(active_product.get("sku") or active_product.get("master_code") or "").strip()
                ] if str(active_product.get("sku") or active_product.get("master_code") or "").strip() else [],
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
                active_product=dict(active_product),
                referenced_products=[dict(active_product)],
            )
        if len(displayed_products) == 1:
            resolved_active = _active_from_displayed(
                displayed_products[0],
                source="single_result",
                confidence=0.85,
                now=now,
            )
            debug["previous_products_used"] = True
            return ContextResolution(
                context_type="detail_reference",
                uses_previous_context=True,
                confidence=0.85,
                reason="Single displayed product follow-up",
                merged_attribute_filters=dict(previous_filters),
                resolved_product_anchor_ids=_anchor_ids_from_products(displayed_products[:1]),
                resolved_product_anchor_skus=_anchor_skus_from_products(displayed_products[:1]),
                bypass_missing_anchor_clarify=True,
                should_clarify=False,
                clarification_reason=None,
                safe_to_retrieve=True,
                debug=debug,
                context_action="reuse",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
                active_product=resolved_active,
                referenced_products=[dict(displayed_products[0])],
            )
        if displayed_products or previous_product_ids:
            return ContextResolution(
                context_type="detail_reference",
                uses_previous_context=False,
                confidence=0.4,
                reason="Vague product reference with multiple possible products",
                merged_attribute_filters=dict(previous_filters),
                bypass_missing_anchor_clarify=False,
                should_clarify=True,
                clarification_reason="product_anchor_ambiguous",
                safe_to_retrieve=False,
                debug=debug,
                context_action="clarify",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
            )
        return ContextResolution(
            context_type="detail_reference",
            uses_previous_context=False,
            confidence=0.35,
            reason="Product-specific question without an anchor",
            merged_attribute_filters=dict(previous_filters),
            bypass_missing_anchor_clarify=False,
            should_clarify=True,
            clarification_reason="product_anchor_missing",
            safe_to_retrieve=False,
            debug=debug,
            context_action="clarify",
            resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
        )

    if current_filters:
        merged = dict(current_filters)
        uses_previous_context = False
        if previous_filters and not context_policy.filters_expired(state, now=now):
            merged = _merge_filters(previous=previous_filters, current=current_filters)
            uses_previous_context = True
            debug["previous_filters_used"] = True
        context_type = "filter_refinement" if _has_strict_followup_marker(user_message) else "attribute_followup"
        confidence = 0.8 if uses_previous_context else 0.75
        return ContextResolution(
            context_type=context_type,
            uses_previous_context=uses_previous_context,
            confidence=confidence,
            reason="Attribute follow-up merged with previous search filters" if uses_previous_context else "Standalone searchable product filters",
            merged_query=_build_merged_query(merged, fallback_query=user_message),
            merged_attribute_filters=merged,
            bypass_missing_anchor_clarify=uses_previous_context,
            should_clarify=False,
            clarification_reason=None,
            safe_to_retrieve=True,
            debug=debug,
            context_action="update" if merged != previous_filters else "reuse",
            resolved_intent="product_search",
        )

    if pending_task and pending_missing_slot == "product_anchor" and _response_policy_from(decision_state) == "ask_clarifying_question":
        return ContextResolution(
            context_type="pending_task_resume",
            uses_previous_context=False,
            confidence=0.3,
            reason="Pending product-anchor task still needs an anchor",
            merged_attribute_filters=dict(previous_filters),
            resume_pending_task=False,
            pending_task_type=pending_task_type,
            bypass_missing_anchor_clarify=False,
            should_clarify=True,
            clarification_reason="product_anchor_missing",
            safe_to_retrieve=False,
            debug=debug,
            context_action="clarify",
            resolved_intent="clarification_response",
        )

    return ContextResolution(
        context_type="none",
        uses_previous_context=False,
        confidence=0.0,
        reason="No reusable context signal",
        merged_query=_build_merged_query(_clean_filter_map(extracted_filters), fallback_query=user_message),
        merged_attribute_filters=dict(_clean_filter_map(extracted_filters)),
        bypass_missing_anchor_clarify=False,
        should_clarify=False,
        clarification_reason=None,
        safe_to_retrieve=False,
        debug=debug,
        context_action="ignore",
        resolved_intent="knowledge_question" if str(workflow or "").strip().lower() == "knowledge" else "unknown",
    )
