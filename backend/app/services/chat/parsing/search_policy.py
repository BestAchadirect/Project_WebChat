from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence, Tuple

from app.services.chat.parsing.attribute_normalization import normalize_attribute_value
from app.services.chat.parsing.attribute_keys import ATTRIBUTE_KEY_ALIASES, canonicalize_filter_key

ALLOWED_PRODUCT_FILTERS = frozenset(
    {
        "min_price",
        "max_price",
        "stock_status",
        "category",
        "body_location",
        "feature",
        "presentation_type",
        "material",
        "jewelry_type",
        "color",
        "theme",
    }
)

HARD_FILTER_KEYS = frozenset(
    {
        "body_location",
        "jewelry_type",
        "material",
        "gauge",
        "feature",
        "presentation_type",
        "threading",
        "size",
        "length",
        "outer_diameter",
        "height",
        "ring_size",
        "pincher_size",
        "min_price",
        "max_price",
        "stock_status",
    }
)

def detect_attribute_list_target(text: str) -> str:
    return ""


def is_attribute_list_query(text: str) -> bool:
    return False


def needs_body_part_suitability_clarification(text: str) -> bool:
    return False


def split_hard_and_soft_filters(
    *,
    attribute_filters: Dict[str, str],
    strictness: Mapping[str, Any] | None = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    hard_filters: Dict[str, str] = {}
    soft_filters: Dict[str, str] = {}
    strictness_map = {
        canonicalize_filter_key(key): str(value or "").strip().lower()
        for key, value in dict(strictness or {}).items()
        if canonicalize_filter_key(key)
    }
    for key, value in dict(attribute_filters or {}).items():
        clean_key = canonicalize_filter_key(key)
        clean_value = str(value or "").strip()
        if not clean_key or not clean_value:
            continue
        strictness_value = strictness_map.get(clean_key)
        if strictness_value == "required" or clean_key in HARD_FILTER_KEYS:
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
        canonicalize_filter_key(key): canonicalize_filter_key(value)
        for key, value in dict(key_aliases or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    clean: Dict[str, Any] = {}
    for key, value in dict(filters or {}).items():
        clean_key = canonicalize_filter_key(key)
        clean_key = aliases.get(clean_key, clean_key)
        if allowed and clean_key not in allowed:
            continue
        if value is None:
            continue
        clean_value = normalize_attribute_value(key=clean_key, value=value)
        if clean_value:
            clean[clean_key] = clean_value
    return clean
