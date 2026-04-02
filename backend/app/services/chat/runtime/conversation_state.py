from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

CONVERSATION_STATE_VERSION = 3
MAX_PRODUCT_IDS = 10
MAX_PRODUCT_SKUS = 10
MAX_SOURCE_IDS = 10
MAX_TONE_RECENT = 8


def _default_state() -> Dict[str, Any]:
    return {
        "version": CONVERSATION_STATE_VERSION,
        "last_workflow": "",
        "last_refined_query": "",
        "last_user_query": "",
        "last_attribute_filters": {},
        "last_requested_fields": [],
        "last_query_cache_key": "",
        "last_query_product_ids": [],
        "last_result_count": 0,
        "last_display_offset": 0,
        "last_display_limit": 0,
        "last_product_ids": [],
        "last_product_skus": [],
        "last_currency": "",
        "last_route": "",
        "last_answer_source_ids": [],
        "last_inventory_claim": {
            "sku": "",
            "stock_status": "",
            "last_stock_sync_at": "",
        },
        "tone_recent": [],
        "updated_at": "",
    }


@dataclass(frozen=True)
class ConversationMemoryState:
    version: int
    last_workflow: str = ""
    last_refined_query: str = ""
    last_user_query: str = ""
    last_attribute_filters: Dict[str, str] = field(default_factory=dict)
    last_requested_fields: List[str] = field(default_factory=list)
    last_product_ids: List[str] = field(default_factory=list)
    last_product_skus: List[str] = field(default_factory=list)
    last_currency: str = ""
    last_route: str = ""
    last_answer_source_ids: List[str] = field(default_factory=list)
    last_inventory_claim: Dict[str, str] = field(default_factory=dict)
    tone_recent: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": int(self.version or CONVERSATION_STATE_VERSION),
            "last_workflow": self.last_workflow,
            "last_refined_query": self.last_refined_query,
            "last_user_query": self.last_user_query,
            "last_attribute_filters": dict(self.last_attribute_filters or {}),
            "last_requested_fields": list(self.last_requested_fields or []),
            "last_product_ids": list(self.last_product_ids or []),
            "last_product_skus": list(self.last_product_skus or []),
            "last_currency": self.last_currency,
            "last_route": self.last_route,
            "last_answer_source_ids": list(self.last_answer_source_ids or []),
            "last_inventory_claim": dict(self.last_inventory_claim or {}),
            "tone_recent": list(self.tone_recent or []),
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ConversationContinuationState:
    last_query_cache_key: str = ""
    last_query_product_ids: List[str] = field(default_factory=list)
    last_result_count: int = 0
    last_display_offset: int = 0
    last_display_limit: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_query_cache_key": self.last_query_cache_key,
            "last_query_product_ids": list(self.last_query_product_ids or []),
            "last_result_count": int(self.last_result_count or 0),
            "last_display_offset": int(self.last_display_offset or 0),
            "last_display_limit": int(self.last_display_limit or 0),
        }


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_currency(value: Any) -> str:
    return _clean_text(value).upper()


def _clean_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _clean_requested_fields(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    fields: List[str] = []
    seen: set[str] = set()
    for item in value:
        field = _clean_text(item).lower()
        if not field or field in seen:
            continue
        seen.add(field)
        fields.append(field)
    return fields


def _clean_attribute_filters(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    cleaned: Dict[str, str] = {}
    for key, raw in value.items():
        clean_key = _clean_text(key).lower()
        clean_value = _clean_text(raw)
        if not clean_key or not clean_value:
            continue
        cleaned[clean_key] = clean_value
    return cleaned


def _clean_product_ids(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    ids: List[str] = []
    seen: set[str] = set()
    for item in values:
        product_id = _clean_text(item)
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        ids.append(product_id)
        if len(ids) >= MAX_PRODUCT_IDS:
            break
    return ids


def _clean_query_product_ids(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    ids: List[str] = []
    seen: set[str] = set()
    for item in values:
        product_id = _clean_text(item)
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        ids.append(product_id)
    return ids


def _clean_product_skus(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    skus: List[str] = []
    seen: set[str] = set()
    for item in values:
        sku = _clean_text(item)
        if not sku:
            continue
        key = sku.lower()
        if key in seen:
            continue
        seen.add(key)
        skus.append(sku)
        if len(skus) >= MAX_PRODUCT_SKUS:
            break
    return skus


def _clean_source_ids(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    source_ids: List[str] = []
    seen: set[str] = set()
    for item in values:
        source_id = _clean_text(item)
        if not source_id:
            continue
        key = source_id.lower()
        if key in seen:
            continue
        seen.add(key)
        source_ids.append(source_id)
        if len(source_ids) >= MAX_SOURCE_IDS:
            break
    return source_ids


def _clean_inventory_claim(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {
            "sku": "",
            "stock_status": "",
            "last_stock_sync_at": "",
        }
    return {
        "sku": _clean_text(value.get("sku")),
        "stock_status": _clean_text(value.get("stock_status")).lower(),
        "last_stock_sync_at": _clean_text(value.get("last_stock_sync_at")),
    }


def _clean_tone_recent(values: Any) -> List[Dict[str, Any]]:
    if not isinstance(values, list):
        return []
    recent: List[Dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("key")).lower()
        style = _clean_text(item.get("style")).lower()
        if style not in {"casual", "neutral", "direct"}:
            style = "neutral"
        try:
            variant_id = int(item.get("variant_id", -1))
        except Exception:
            variant_id = -1
        if not key or variant_id < 0:
            continue
        recent.append(
            {
                "key": key,
                "style": style,
                "variant_id": int(variant_id),
            }
        )
    return recent[-MAX_TONE_RECENT:]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state(raw: Any) -> Dict[str, Any]:
    base = _default_state()
    if not isinstance(raw, dict):
        return base

    normalized = dict(raw)
    try:
        version = int(raw.get("version", CONVERSATION_STATE_VERSION) or CONVERSATION_STATE_VERSION)
    except Exception:
        version = CONVERSATION_STATE_VERSION
    if version <= 0:
        version = CONVERSATION_STATE_VERSION

    normalized["version"] = version
    normalized["last_workflow"] = _clean_text(raw.get("last_workflow"))
    normalized["last_refined_query"] = _clean_text(raw.get("last_refined_query"))
    normalized["last_user_query"] = _clean_text(raw.get("last_user_query"))
    normalized["last_attribute_filters"] = _clean_attribute_filters(raw.get("last_attribute_filters"))
    normalized["last_requested_fields"] = _clean_requested_fields(raw.get("last_requested_fields"))
    normalized["last_query_cache_key"] = _clean_text(raw.get("last_query_cache_key"))
    normalized["last_query_product_ids"] = _clean_query_product_ids(raw.get("last_query_product_ids"))
    normalized["last_result_count"] = _clean_int(raw.get("last_result_count"))
    normalized["last_display_offset"] = _clean_int(raw.get("last_display_offset"))
    normalized["last_display_limit"] = _clean_int(raw.get("last_display_limit"))
    normalized["last_product_ids"] = _clean_product_ids(raw.get("last_product_ids"))
    normalized["last_product_skus"] = _clean_product_skus(raw.get("last_product_skus"))
    normalized["last_currency"] = _clean_currency(raw.get("last_currency"))
    normalized["last_route"] = _clean_text(raw.get("last_route"))
    normalized["last_answer_source_ids"] = _clean_source_ids(raw.get("last_answer_source_ids"))
    normalized["last_inventory_claim"] = _clean_inventory_claim(raw.get("last_inventory_claim"))
    normalized["tone_recent"] = _clean_tone_recent(raw.get("tone_recent"))
    normalized["updated_at"] = _clean_text(raw.get("updated_at"))

    for key, value in base.items():
        normalized.setdefault(key, value)
    return normalized


def load_memory_state(raw: Any) -> ConversationMemoryState:
    state = load_state(raw)
    return ConversationMemoryState(
        version=int(state.get("version", CONVERSATION_STATE_VERSION) or CONVERSATION_STATE_VERSION),
        last_workflow=_clean_text(state.get("last_workflow")),
        last_refined_query=_clean_text(state.get("last_refined_query")),
        last_user_query=_clean_text(state.get("last_user_query")),
        last_attribute_filters=_clean_attribute_filters(state.get("last_attribute_filters")),
        last_requested_fields=_clean_requested_fields(state.get("last_requested_fields")),
        last_product_ids=_clean_product_ids(state.get("last_product_ids")),
        last_product_skus=_clean_product_skus(state.get("last_product_skus")),
        last_currency=_clean_currency(state.get("last_currency")),
        last_route=_clean_text(state.get("last_route")),
        last_answer_source_ids=_clean_source_ids(state.get("last_answer_source_ids")),
        last_inventory_claim=_clean_inventory_claim(state.get("last_inventory_claim")),
        tone_recent=_clean_tone_recent(state.get("tone_recent")),
        updated_at=_clean_text(state.get("updated_at")),
    )


def load_continuation_state(raw: Any) -> ConversationContinuationState:
    state = load_state(raw)
    return ConversationContinuationState(
        last_query_cache_key=_clean_text(state.get("last_query_cache_key")),
        last_query_product_ids=_clean_query_product_ids(state.get("last_query_product_ids")),
        last_result_count=_clean_int(state.get("last_result_count")),
        last_display_offset=_clean_int(state.get("last_display_offset")),
        last_display_limit=_clean_int(state.get("last_display_limit")),
    )


def split_state(raw: Any) -> tuple[ConversationMemoryState, ConversationContinuationState]:
    return load_memory_state(raw), load_continuation_state(raw)


def build_state_payload(
    *,
    memory: ConversationMemoryState,
    continuation: ConversationContinuationState,
) -> Dict[str, Any]:
    merged = _default_state()
    merged.update(memory.to_dict())
    merged.update(continuation.to_dict())
    merged["version"] = int(memory.version or CONVERSATION_STATE_VERSION)
    return merged

def apply_workflow_update(
    state: Any,
    *,
    workflow: str,
    refined_query: str,
    attribute_filters: Any,
) -> Dict[str, Any]:
    memory, continuation = split_state(state)
    updated_memory = ConversationMemoryState(
        version=memory.version,
        last_workflow=_clean_text(workflow),
        last_refined_query=_clean_text(refined_query),
        last_user_query=_clean_text(refined_query),
        last_attribute_filters=_clean_attribute_filters(attribute_filters),
        last_requested_fields=list(memory.last_requested_fields or []),
        last_product_ids=list(memory.last_product_ids or []),
        last_product_skus=list(memory.last_product_skus or []),
        last_currency=memory.last_currency,
        last_route=memory.last_route,
        last_answer_source_ids=list(memory.last_answer_source_ids or []),
        last_inventory_claim=dict(memory.last_inventory_claim or {}),
        tone_recent=list(memory.tone_recent or []),
        updated_at=memory.updated_at,
    )
    return build_state_payload(memory=updated_memory, continuation=continuation)


def apply_retrieval_update(
    state: Any,
    *,
    product_ids: Any,
    product_skus: Any = None,
    route: str,
) -> Dict[str, Any]:
    memory, continuation = split_state(state)
    updated_memory = ConversationMemoryState(
        version=memory.version,
        last_workflow=memory.last_workflow,
        last_refined_query=memory.last_refined_query,
        last_user_query=memory.last_user_query,
        last_attribute_filters=dict(memory.last_attribute_filters or {}),
        last_requested_fields=list(memory.last_requested_fields or []),
        last_product_ids=_clean_product_ids(product_ids),
        last_product_skus=_clean_product_skus(product_skus) if product_skus is not None else list(memory.last_product_skus or []),
        last_currency=memory.last_currency,
        last_route=_clean_text(route),
        last_answer_source_ids=list(memory.last_answer_source_ids or []),
        last_inventory_claim=dict(memory.last_inventory_claim or {}),
        tone_recent=list(memory.tone_recent or []),
        updated_at=memory.updated_at,
    )
    return build_state_payload(memory=updated_memory, continuation=continuation)


def apply_response_update(
    state: Any,
    *,
    requested_fields: Any,
    currency: str,
    route: str,
    query_cache_key: str = "",
    query_product_ids: Any = None,
    result_count: Optional[int] = None,
    display_offset: Optional[int] = None,
    display_limit: Optional[int] = None,
    product_ids: Any = None,
    product_skus: Any = None,
    answer_source_ids: Any = None,
    inventory_claim: Any = None,
    tone_recent: Any = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    memory, continuation = split_state(state)
    updated_memory = ConversationMemoryState(
        version=memory.version,
        last_workflow=memory.last_workflow,
        last_refined_query=memory.last_refined_query,
        last_user_query=memory.last_user_query,
        last_attribute_filters=dict(memory.last_attribute_filters or {}),
        last_requested_fields=_clean_requested_fields(requested_fields),
        last_product_ids=_clean_product_ids(product_ids) if product_ids is not None else list(memory.last_product_ids or []),
        last_product_skus=_clean_product_skus(product_skus) if product_skus is not None else list(memory.last_product_skus or []),
        last_currency=_clean_currency(currency),
        last_route=_clean_text(route),
        last_answer_source_ids=_clean_source_ids(answer_source_ids) if answer_source_ids is not None else list(memory.last_answer_source_ids or []),
        last_inventory_claim=_clean_inventory_claim(inventory_claim) if inventory_claim is not None else dict(memory.last_inventory_claim or {}),
        tone_recent=_clean_tone_recent(tone_recent) if tone_recent is not None else list(memory.tone_recent or []),
        updated_at=_clean_text(updated_at) or utc_timestamp(),
    )
    updated_continuation = ConversationContinuationState(
        last_query_cache_key=_clean_text(query_cache_key) if query_cache_key is not None else continuation.last_query_cache_key,
        last_query_product_ids=_clean_query_product_ids(query_product_ids) if query_product_ids is not None else list(continuation.last_query_product_ids or []),
        last_result_count=_clean_int(result_count) if result_count is not None else continuation.last_result_count,
        last_display_offset=_clean_int(display_offset) if display_offset is not None else continuation.last_display_offset,
        last_display_limit=_clean_int(display_limit) if display_limit is not None else continuation.last_display_limit,
    )
    return build_state_payload(memory=updated_memory, continuation=updated_continuation)


def product_ids_from_cards(cards: Optional[Iterable[Any]]) -> List[str]:
    ids: List[str] = []
    seen: set[str] = set()
    for card in cards or []:
        product_id = _clean_text(getattr(card, "id", None))
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        ids.append(product_id)
        if len(ids) >= MAX_PRODUCT_IDS:
            break
    return ids


def product_skus_from_cards(cards: Optional[Iterable[Any]]) -> List[str]:
    skus: List[str] = []
    seen: set[str] = set()
    for card in cards or []:
        sku = _clean_text(getattr(card, "sku", None))
        if not sku:
            continue
        key = sku.lower()
        if key in seen:
            continue
        seen.add(key)
        skus.append(sku)
        if len(skus) >= MAX_PRODUCT_SKUS:
            break
    return skus
