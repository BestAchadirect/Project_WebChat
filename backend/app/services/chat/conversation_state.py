from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, Iterable, List, Optional

CONVERSATION_STATE_VERSION = 1
MAX_PRODUCT_IDS = 10

_FOLLOW_UP_TOKENS = {
    "another",
    "any",
    "better",
    "cheaper",
    "cheapest",
    "else",
    "first",
    "it",
    "less",
    "more",
    "one",
    "ones",
    "same",
    "second",
    "similar",
    "that",
    "them",
    "these",
    "third",
    "those",
}


def _default_state() -> Dict[str, Any]:
    return {
        "version": CONVERSATION_STATE_VERSION,
        "last_intent": "",
        "last_refined_query": "",
        "last_attribute_filters": {},
        "last_requested_fields": [],
        "last_product_ids": [],
        "last_currency": "",
        "last_route": "",
        "updated_at": "",
    }


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_currency(value: Any) -> str:
    return _clean_text(value).upper()


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
    normalized["last_intent"] = _clean_text(raw.get("last_intent"))
    normalized["last_refined_query"] = _clean_text(raw.get("last_refined_query"))
    normalized["last_attribute_filters"] = _clean_attribute_filters(raw.get("last_attribute_filters"))
    normalized["last_requested_fields"] = _clean_requested_fields(raw.get("last_requested_fields"))
    normalized["last_product_ids"] = _clean_product_ids(raw.get("last_product_ids"))
    normalized["last_currency"] = _clean_currency(raw.get("last_currency"))
    normalized["last_route"] = _clean_text(raw.get("last_route"))
    normalized["updated_at"] = _clean_text(raw.get("updated_at"))

    for key, value in base.items():
        normalized.setdefault(key, value)
    return normalized


def merge_filters(current_filters: Any, previous_filters: Any) -> Dict[str, str]:
    merged = _clean_attribute_filters(previous_filters)
    merged.update(_clean_attribute_filters(current_filters))
    return merged


def should_merge_follow_up_filters(
    *,
    user_text: str,
    current_filters: Any,
    sku_token: Optional[str],
) -> bool:
    if sku_token or _clean_attribute_filters(current_filters):
        return False

    normalized = _clean_text(user_text).lower()
    if not normalized:
        return False

    tokens = re.findall(r"[a-z0-9]+", normalized)
    if not tokens or len(tokens) > 8:
        return False
    return any(token in _FOLLOW_UP_TOKENS for token in tokens)


def apply_intent_update(
    state: Any,
    *,
    intent: str,
    refined_query: str,
    attribute_filters: Any,
) -> Dict[str, Any]:
    updated = load_state(state)
    updated["last_intent"] = _clean_text(intent)
    updated["last_refined_query"] = _clean_text(refined_query)
    updated["last_attribute_filters"] = _clean_attribute_filters(attribute_filters)
    return updated


def apply_retrieval_update(
    state: Any,
    *,
    product_ids: Any,
    route: str,
) -> Dict[str, Any]:
    updated = load_state(state)
    updated["last_product_ids"] = _clean_product_ids(product_ids)
    updated["last_route"] = _clean_text(route)
    return updated


def apply_response_update(
    state: Any,
    *,
    requested_fields: Any,
    currency: str,
    route: str,
    product_ids: Any = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    updated = load_state(state)
    updated["last_requested_fields"] = _clean_requested_fields(requested_fields)
    updated["last_currency"] = _clean_currency(currency)
    updated["last_route"] = _clean_text(route)
    if product_ids is not None:
        updated["last_product_ids"] = _clean_product_ids(product_ids)
    updated["updated_at"] = _clean_text(updated_at) or utc_timestamp()
    return updated


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
