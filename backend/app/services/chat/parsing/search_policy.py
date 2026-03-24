from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Sequence, Tuple

from app.services.chat.parsing.attribute_normalization import normalize_text

ALLOWED_PRODUCT_FILTERS = frozenset(
    {
        "min_price",
        "max_price",
        "stock_status",
        "category",
        "material",
        "jewelry_type",
        "color",
    }
)

ATTRIBUTE_LIST_TERMS = {
    "material": "material",
    "materials": "material",
    "color": "color",
    "colors": "color",
    "gauge": "gauge",
    "gauges": "gauge",
    "threading": "threading",
    "threadings": "threading",
    "type": "jewelry_type",
    "types": "jewelry_type",
}

HARD_FILTER_KEYS = frozenset(
    {
        "gauge",
        "threading",
        "size",
        "length",
        "outer_diameter",
        "height",
        "ring_size",
        "pincher_size",
    }
)


def detect_attribute_list_target(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return ""
    asks_for_list = bool(
        re.search(r"\b(what|which|list|show|available|sell|have|offer|carry)\b", normalized)
        or normalized.endswith("?")
    )
    if not asks_for_list:
        return ""
    for token, target in ATTRIBUTE_LIST_TERMS.items():
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            return target
    return ""


def split_hard_and_soft_filters(
    *,
    attribute_filters: Dict[str, str],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    hard_filters: Dict[str, str] = {}
    soft_filters: Dict[str, str] = {}
    for key, value in dict(attribute_filters or {}).items():
        clean_key = str(key or "").strip().lower()
        clean_value = str(value or "").strip()
        if not clean_key or not clean_value:
            continue
        if clean_key in HARD_FILTER_KEYS:
            hard_filters[clean_key] = clean_value
        else:
            soft_filters[clean_key] = clean_value
    return hard_filters, soft_filters


def normalize_filter_map(
    filters: Mapping[str, Any] | None,
    *,
    allowed_keys: Sequence[str] | frozenset[str] | None = None,
    key_aliases: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    allowed = {
        str(item or "").strip().lower()
        for item in list(allowed_keys or [])
        if str(item or "").strip()
    }
    aliases = {
        str(key or "").strip().lower(): str(value or "").strip().lower()
        for key, value in dict(key_aliases or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    clean: Dict[str, Any] = {}
    for key, value in dict(filters or {}).items():
        clean_key = str(key or "").strip().lower()
        clean_key = aliases.get(clean_key, clean_key)
        if allowed and clean_key not in allowed:
            continue
        if value is None:
            continue
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                continue
            clean[clean_key] = trimmed
        else:
            clean[clean_key] = value
    return clean
