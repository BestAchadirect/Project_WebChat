from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Sequence, Tuple

from app.services.chat.parsing.attribute_normalization import (
    normalize_catalog_family_value,
    normalize_text,
)
from app.utils.synonym_rules import (
    ATTRIBUTE_LIST_QUERY_SYNONYMS,
    ATTRIBUTE_LIST_TARGETS,
    BODY_PART_SUITABILITY_AMBIGUOUS_MODIFIERS,
    BODY_PART_SUITABILITY_TERMS,
)

ALLOWED_PRODUCT_FILTERS = frozenset(
    {
        "min_price",
        "max_price",
        "stock_status",
        "category",
        "body_part",
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
        "body_part",
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
    }
)


def detect_attribute_list_target(text: str) -> str:
    if not is_attribute_list_query(text):
        return ""
    normalized = normalize_text(text)
    for token, target in ATTRIBUTE_LIST_QUERY_SYNONYMS.items():
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            return target
    return ""


def is_attribute_list_query(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    return bool(
        re.search(r"\b(what|which|list|show|available|sell|have|offer|carry)\b", normalized)
        or normalized.endswith("?")
    )


def needs_body_part_suitability_clarification(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    modifier_hit = any(re.search(rf"\b{re.escape(modifier)}\b", normalized) for modifier in BODY_PART_SUITABILITY_AMBIGUOUS_MODIFIERS)
    if not modifier_hit:
        return False
    return any(re.search(rf"\b{re.escape(term)}\b", normalized) for term in BODY_PART_SUITABILITY_TERMS)


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
            family_value = normalize_catalog_family_value(key=clean_key, value=trimmed)
            clean[clean_key] = family_value or trimmed
        else:
            clean[clean_key] = value
    return clean
