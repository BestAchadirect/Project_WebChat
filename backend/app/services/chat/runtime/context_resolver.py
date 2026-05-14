from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.chat.routing import routing_policy
from app.services.chat.runtime import context_policy, conversation_state
from app.services.chat.text_normalization import normalize_user_text

CONTEXT_USE_THRESHOLD = 0.80
CONTEXT_CLARIFY_THRESHOLD = 0.50


@dataclass(frozen=True)
class ContextResolution:
    context_used: bool
    context_action: str
    resolved_intent: str
    resolved_filters: Dict[str, str] = field(default_factory=dict)
    active_product: Optional[Dict[str, Any]] = None
    referenced_products: List[Dict[str, Any]] = field(default_factory=list)
    pagination_action: Optional[Dict[str, Any]] = None
    pending_task_action: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    reason: str = ""
    reset_reason: Optional[str] = None
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_debug_dict(self) -> Dict[str, Any]:
        return {
            "context_used": bool(self.context_used),
            "context_action": self.context_action,
            "resolved_intent": self.resolved_intent,
            "resolved_filters": dict(self.resolved_filters or {}),
            "active_product": dict(self.active_product or {}),
            "referenced_products": [dict(item) for item in list(self.referenced_products or [])],
            "pagination_action": dict(self.pagination_action or {}) if self.pagination_action else None,
            "pending_task_action": dict(self.pending_task_action or {}) if self.pending_task_action else None,
            "confidence": float(self.confidence or 0.0),
            "reason": self.reason,
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
    return {
        "product_id": "",
        "sku": str(sku or "").strip(),
        "master_code": str(sku or "").strip(),
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


def resolve_context(
    *,
    user_message: str,
    conversation_id: Any,
    loaded_state: Any,
    workflow: str = "",
    extracted_filters: Mapping[str, Any] | None = None,
    requested_fields: Sequence[str] | None = None,
    sku_tokens: Sequence[str] | None = None,
    client_action: str = "",
    client_action_payload: Mapping[str, Any] | None = None,
    now: Optional[datetime] = None,
) -> ContextResolution:
    state = conversation_state.load_state(loaded_state)
    normalized = normalize_user_text(user_message)
    previous_filters = _clean_filter_map(state.get("last_attribute_filters"))
    extracted_clean = _clean_filter_map(extracted_filters)
    text_filter_overrides = context_policy.extract_filter_overrides(user_message)
    if previous_filters and not context_policy.has_explicit_product_type_signal(user_message):
        # Short refinements like "what about gold?" should not let isolated LLM
        # extraction replace the previous product anchor.
        extracted_clean.pop("jewelry_type", None)
        extracted_clean.pop("category", None)
    current_filters = _merge_filters(
        previous=extracted_clean,
        current=text_filter_overrides,
    )
    displayed_products = [
        dict(item)
        for item in list(state.get("displayed_products") or [])
        if isinstance(item, dict)
    ]
    active_product = dict(state.get("active_product") or {})
    pending_task = dict(state.get("pending_task") or {})
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
    debug = {
        "conversation_id": str(conversation_id or ""),
        "user_message": str(user_message or "")[:500],
        "previous_context_summary": _summary_from_state(state),
        "current_filters": dict(current_filters),
        "sku_tokens": list(sku_list),
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
        display_offset = int(client_payload.get("display_offset") or state.get("last_display_offset") or 0)
        display_limit = int(client_payload.get("display_limit") or state.get("last_display_limit") or 0)
        result_count = int(state.get("last_result_count") or 0)
        has_page = bool(query_ids or query_key)
        action = {
            "query_cache_key": query_key,
            "query_product_ids": query_ids,
            "display_offset": display_offset,
            "display_limit": display_limit,
            "result_count": result_count,
        }
        return ContextResolution(
            context_used=has_page,
            context_action="reuse" if has_page else "clarify",
            resolved_intent="pagination",
            resolved_filters=dict(previous_filters),
            pagination_action=action if has_page else None,
            confidence=0.9 if has_page else 0.35,
            reason="Pagination follow-up" if has_page else "Pagination requested without valid previous page",
            debug=debug,
        )

    if sku_list:
        sku_active = _active_from_sku(sku_list[0], now=now)
        debug["resolved_context"] = {"active_product": sku_active}
        return ContextResolution(
            context_used=True,
            context_action="reset",
            resolved_intent="product_detail",
            resolved_filters=dict(current_filters),
            active_product=sku_active,
            referenced_products=[sku_active],
            confidence=0.95,
            reason="Explicit SKU or master-code reference",
            reset_reason="explicit_sku",
            debug=debug,
        )

    reset_reason = context_policy.topic_switch_reason(
        text=user_message,
        previous_filters=previous_filters,
        current_filters=current_filters,
    )
    if reset_reason:
        return ContextResolution(
            context_used=False,
            context_action="reset",
            resolved_intent="product_search" if current_filters else "unknown",
            resolved_filters=dict(current_filters),
            active_product=None,
            confidence=0.88 if current_filters else 0.7,
            reason="Topic switch reset",
            reset_reason=reset_reason,
            debug=debug,
        )

    position = context_policy.detect_position_reference(user_message, displayed_products)
    if position is not None:
        product = context_policy.find_displayed_product_by_position(displayed_products, position)
        if product:
            resolved_active = _active_from_displayed(
                product,
                source="position_reference",
                confidence=0.9,
                now=now,
            )
            return ContextResolution(
                context_used=True,
                context_action="reuse",
                resolved_intent=_resolved_intent_from_detail(user_message, workflow, requested) or "product_detail",
                resolved_filters=dict(previous_filters),
                active_product=resolved_active,
                referenced_products=[dict(product)],
                pending_task_action={"action": "resume", "clear": True} if pending_task else None,
                confidence=0.9,
                reason="Position reference resolved from displayed products",
                debug=debug,
            )
        return ContextResolution(
            context_used=False,
            context_action="clarify",
            resolved_intent="product_detail",
            resolved_filters=dict(previous_filters),
            confidence=0.4,
            reason="Position reference did not match displayed products",
            debug=debug,
        )

    if pending_task and str(pending_task.get("missing_slot") or "").strip().lower() == "product_anchor":
        descriptor_match = context_policy.find_displayed_product_by_descriptor(displayed_products, user_message)
        if descriptor_match:
            resolved_active = _active_from_displayed(
                descriptor_match,
                source="inferred_followup",
                confidence=0.8,
                now=now,
            )
            return ContextResolution(
                context_used=True,
                context_action="reuse",
                resolved_intent="clarification_response",
                resolved_filters=dict(previous_filters),
                active_product=resolved_active,
                referenced_products=[descriptor_match],
                pending_task_action={"action": "resume", "clear": True},
                confidence=0.8,
                reason="Pending product-anchor clarification answered",
                debug=debug,
            )

    detail_intent = _resolved_intent_from_detail(user_message, workflow, requested)
    sensitive_detail = context_policy.is_product_sensitive_detail(user_message, list(requested))
    pronoun_reference = context_policy.has_pronoun_product_reference(user_message)
    active_is_valid = bool(active_product) and not context_policy.active_product_expired(active_product, now=now)
    if sensitive_detail or pronoun_reference:
        if active_is_valid:
            return ContextResolution(
                context_used=True,
                context_action="reuse",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
                resolved_filters=dict(previous_filters),
                active_product=dict(active_product),
                referenced_products=[dict(active_product)],
                confidence=0.85,
                reason="Single active product follow-up",
                debug=debug,
            )
        if len(displayed_products) == 1:
            product = displayed_products[0]
            resolved_active = _active_from_displayed(
                product,
                source="single_result",
                confidence=0.85,
                now=now,
            )
            return ContextResolution(
                context_used=True,
                context_action="reuse",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
                resolved_filters=dict(previous_filters),
                active_product=resolved_active,
                referenced_products=[dict(product)],
                confidence=0.85,
                reason="Single displayed product follow-up",
                debug=debug,
            )
        if (displayed_products or state.get("last_product_ids")) and not current_filters:
            return ContextResolution(
                context_used=False,
                context_action="clarify",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
                resolved_filters=dict(previous_filters),
                confidence=0.4,
                reason="Vague product reference with multiple possible products",
                debug=debug,
            )
        if not current_filters:
            return ContextResolution(
                context_used=False,
                context_action="clarify",
                resolved_intent=detail_intent if detail_intent != "unknown" else "product_detail",
                confidence=0.35,
                reason="Product-specific question without active product",
                debug=debug,
            )

    if current_filters:
        if previous_filters and not context_policy.filters_expired(state, now=now):
            merged = _merge_filters(previous=previous_filters, current=current_filters)
            action = "update" if merged != previous_filters else "reuse"
            return ContextResolution(
                context_used=True,
                context_action=action,
                resolved_intent="product_search",
                resolved_filters=merged,
                confidence=0.8,
                reason="Attribute-only follow-up after product search",
                debug=debug,
            )
        return ContextResolution(
            context_used=bool(current_filters),
            context_action="update",
            resolved_intent="product_search",
            resolved_filters=dict(current_filters),
            confidence=0.75,
            reason="Standalone product filters without reusable prior context",
            debug=debug,
        )

    return ContextResolution(
        context_used=False,
        context_action="ignore",
        resolved_intent="knowledge_question" if str(workflow or "").strip().lower() == "knowledge" else "unknown",
        resolved_filters=dict(_clean_filter_map(extracted_filters)),
        confidence=0.0,
        reason="No reusable context signal",
        debug=debug,
    )
