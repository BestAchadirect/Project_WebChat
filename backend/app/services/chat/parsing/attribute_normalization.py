from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.chat.text_normalization import normalize_user_text
from app.services.chat.parsing.attribute_keys import canonicalize_filter_key

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


def _normalize_multivalue_tokens(value: Any) -> List[str]:
    tokens: List[str] = []

    def _collect(raw: Any) -> None:
        if raw is None:
            return
        if isinstance(raw, (list, tuple, set)):
            for nested in raw:
                _collect(nested)
            return
        text = normalize_text(raw)
        if not text:
            return
        if ";;" in text:
            for token in text.split(";;"):
                _collect(token)
            return
        if ";" in text:
            for token in text.split(";"):
                _collect(token)
            return
        tokens.append(text)

    _collect(value)
    deduped: List[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped

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


def normalize_attribute_value(
    *,
    key: str,
    value: Any,
    alias_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    del alias_map
    clean_key = canonicalize_filter_key(key)
    if isinstance(value, (list, tuple, set)) and clean_key != "category":
        value = next((item for item in list(value) if normalize_text(item)), "")
    text = normalize_text(value)
    if not clean_key or not text:
        return ""
    if clean_key == "gauge":
        return normalize_text(text) or text
    if clean_key in _MEASUREMENT_KEYS:
        return normalize_text(text)
    if clean_key in _COMPACT_WHITESPACE_KEYS:
        return _collapse_whitespace(text)
    if clean_key == "category":
        return ";;".join(_normalize_multivalue_tokens(value))
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
        canonicalize_filter_key(item)
        for item in list(allowed_attribute_filters or [])
        if canonicalize_filter_key(item)
    }
    out: Dict[str, str] = {}
    for key, value in raw_filters.items():
        clean_key = canonicalize_filter_key(key)
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
