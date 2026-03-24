from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, Iterable, List, Optional

CONVERSATION_STATE_VERSION = 2
MAX_PRODUCT_IDS = 10
MAX_PRODUCT_SKUS = 10
MAX_SOURCE_IDS = 10
MAX_TONE_RECENT = 8

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
        "last_workflow": "",
        "last_refined_query": "",
        "last_user_query": "",
        "last_attribute_filters": {},
        "last_requested_fields": [],
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


def apply_workflow_update(
    state: Any,
    *,
    workflow: str,
    refined_query: str,
    attribute_filters: Any,
) -> Dict[str, Any]:
    updated = load_state(state)
    updated["last_workflow"] = _clean_text(workflow)
    updated["last_refined_query"] = _clean_text(refined_query)
    updated["last_user_query"] = _clean_text(refined_query)
    updated["last_attribute_filters"] = _clean_attribute_filters(attribute_filters)
    return updated


def apply_retrieval_update(
    state: Any,
    *,
    product_ids: Any,
    product_skus: Any = None,
    route: str,
) -> Dict[str, Any]:
    updated = load_state(state)
    updated["last_product_ids"] = _clean_product_ids(product_ids)
    if product_skus is not None:
        updated["last_product_skus"] = _clean_product_skus(product_skus)
    updated["last_route"] = _clean_text(route)
    return updated


def apply_response_update(
    state: Any,
    *,
    requested_fields: Any,
    currency: str,
    route: str,
    product_ids: Any = None,
    product_skus: Any = None,
    answer_source_ids: Any = None,
    inventory_claim: Any = None,
    tone_recent: Any = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    updated = load_state(state)
    updated["last_requested_fields"] = _clean_requested_fields(requested_fields)
    updated["last_currency"] = _clean_currency(currency)
    updated["last_route"] = _clean_text(route)
    if product_ids is not None:
        updated["last_product_ids"] = _clean_product_ids(product_ids)
    if product_skus is not None:
        updated["last_product_skus"] = _clean_product_skus(product_skus)
    if answer_source_ids is not None:
        updated["last_answer_source_ids"] = _clean_source_ids(answer_source_ids)
    if inventory_claim is not None:
        updated["last_inventory_claim"] = _clean_inventory_claim(inventory_claim)
    if tone_recent is not None:
        updated["tone_recent"] = _clean_tone_recent(tone_recent)
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
