from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Sequence

from app.services.chat.text_normalization import normalize_user_text
from app.utils.synonym_rules import (
    CATALOG_FAMILY_SYNONYMS,
    normalize_design_family_value,
    normalize_family_value,
)

_MEASUREMENT_KEYS = {
    "gauge",
    "length",
    "size",
    "outer_diameter",
    "height",
    "pincher_size",
}

_COMPACT_WHITESPACE_KEYS = {"ring_size", "size_in_pack", "quantity_in_bulk", "rack"}


def _collapse_whitespace(value: Any) -> str:
    return re.sub(r"\s+", " ", normalize_text(value)).strip()


def _normalize_color_like_value(value: Any) -> str:
    return re.sub(r"^(?:in|with)\s+", "", normalize_text(value)).strip()

def normalize_text(value: Any) -> str:
    return normalize_user_text(value)


def normalize_lexical_alias_map(
    raw_map: Mapping[str, Mapping[str, str]] | None,
) -> Dict[str, Dict[str, str]]:
    normalized: Dict[str, Dict[str, str]] = {}
    for raw_attr, raw_values in dict(raw_map or {}).items():
        attr = normalize_text(raw_attr)
        if not attr:
            continue
        bucket = normalized.setdefault(attr, {})
        for raw_value, canonical_value in dict(raw_values or {}).items():
            raw_norm = normalize_text(raw_value)
            canonical_norm = normalize_text(canonical_value)
            if not raw_norm or not canonical_norm:
                continue
            bucket[raw_norm] = canonical_norm
            bucket.setdefault(canonical_norm, canonical_norm)
    return normalized


def normalize_gauge_token(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    mm_match = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*mm\b", text)
    if mm_match and ("gauge" in text or re.fullmatch(r"\d{1,3}(?:\.\d+)?\s*mm", text)):
        return f"{mm_match.group(1)}mm"
    g_match = re.search(r"\b(\d{1,2})\s*(?:g|gauge)\b", text)
    if g_match:
        return f"{g_match.group(1)}g"
    if re.fullmatch(r"\d{1,2}g", text):
        return text
    return ""


def normalize_catalog_family_value(*, key: str, value: Any) -> str:
    return normalize_text(normalize_family_value(family=key, value=value))


def normalize_measurement_token(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    match = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*(mm|cm|in|inch|inches)\b", text)
    if match:
        unit = match.group(2)
        if unit == "inches":
            unit = "inch"
        return f"{match.group(1)}{unit}"
    if re.fullmatch(r"\d{1,3}(?:\.\d+)?", text):
        return text
    return text


def normalize_attribute_value(
    *,
    key: str,
    value: Any,
    alias_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    clean_key = normalize_text(key)
    text = normalize_text(value)
    if not clean_key or not text:
        return ""
    mapped = None
    if alias_map:
        mapped = alias_map.get(clean_key, {}).get(text)
    if mapped:
        text = normalize_text(mapped)
    if clean_key == "gauge":
        return normalize_gauge_token(text) or text
    if clean_key in CATALOG_FAMILY_SYNONYMS:
        return normalize_catalog_family_value(key=clean_key, value=text) or text
    if clean_key in _MEASUREMENT_KEYS:
        return normalize_measurement_token(text)
    if clean_key == "design":
        return normalize_design_family_value(text) or text
    if clean_key in _COMPACT_WHITESPACE_KEYS:
        return _collapse_whitespace(text)
    if clean_key == "category":
        return re.sub(r"\s*;;\s*", ";;", text)
    if clean_key == "color" or clean_key.endswith("_color"):
        return _normalize_color_like_value(text)
    return text


def clean_attribute_filters(
    raw_filters: Any,
    *,
    alias_map: Optional[Dict[str, Dict[str, str]]] = None,
    allowed_attribute_filters: Optional[Sequence[str]] = None,
) -> Dict[str, str]:
    if not isinstance(raw_filters, dict):
        return {}
    allowed = {
        normalize_text(item)
        for item in list(allowed_attribute_filters or [])
        if normalize_text(item)
    }
    out: Dict[str, str] = {}
    for key, value in raw_filters.items():
        clean_key = normalize_text(key)
        if allowed and clean_key not in allowed:
            continue
        clean_value = normalize_attribute_value(
            key=clean_key,
            value=value,
            alias_map=alias_map,
        )
        if clean_value:
            out[clean_key] = clean_value
    return out
