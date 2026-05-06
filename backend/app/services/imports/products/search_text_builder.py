from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Sequence

DEFAULT_ATTRIBUTE_COLUMNS = [
    "body_part",
    "feature",
    "jewelry_type",
    "material",
    "length",
    "size",
    "cz_color",
    "design",
    "crystal_color",
    "color",
    "gauge",
    "size_in_pack",
    "rack",
    "height",
    "packing_option",
    "pincher_size",
    "ring_size",
    "quantity_in_bulk",
    "opal_color",
    "threading",
    "outer_diameter",
    "pearl_color",
    "presentation_type",
    "theme",
]

DEFAULT_SEARCH_KEYWORD_COLUMNS = [
    "body_part",
    "feature",
    "jewelry_type",
    "material",
    "gauge",
    "threading",
    "length",
    "size",
    "color",
    "presentation_type",
    "theme",
]


def normalize_search_text(text: str) -> str:
    if not text:
        return ""
    normalized = html.unescape(text)
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def normalize_keyword(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return normalize_search_text(text)


def normalize_material(value: str) -> str:
    return value.strip()


def normalize_gauge(value: str) -> str:
    lower = value.strip().lower()
    match = re.search(r"\b(\d{1,2})\s*(?:g|gauge)\b", lower)
    if match:
        return f"{match.group(1)}g"
    if lower.endswith("g") and lower[:-1].isdigit():
        return lower
    return value.strip()


def normalize_threading(value: str) -> str:
    return value.strip()


def normalize_presentation_type(value: str) -> str:
    return value.strip()


def normalize_body_part(value: str) -> str:
    return value.strip()


def normalize_theme(value: str) -> str:
    return value.strip()


def normalize_feature(value: str) -> str:
    return value.strip()


def normalize_jewelry_type(value: str) -> str:
    return value.strip()


def normalize_attribute_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if key == "material":
        return normalize_material(text)
    if key == "gauge":
        return normalize_gauge(text)
    if key == "threading":
        return normalize_threading(text)
    if key == "presentation_type":
        return normalize_presentation_type(text)
    if key == "body_part":
        return normalize_body_part(text)
    if key == "theme":
        return normalize_theme(text)
    if key == "feature":
        return normalize_feature(text)
    if key == "jewelry_type":
        return normalize_jewelry_type(text)
    return text


def build_search_keywords(
    *,
    display_name: str,
    sku: str,
    legacy_skus: List[str],
    attributes: Dict[str, Any],
    keyword_columns: List[str] = DEFAULT_SEARCH_KEYWORD_COLUMNS,
) -> List[str]:
    tokens: List[str] = []

    def add(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, list):
            for item in value:
                add(item)
            return
        token = normalize_keyword(value)
        if token:
            tokens.append(token)

    add(display_name)
    add(sku)
    add(legacy_skus)
    for key in keyword_columns:
        add(attributes.get(key))

    seen = set()
    deduped: List[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def expand_search_terms(values: List[Any]) -> List[str]:
    expanded: List[str] = []
    seen = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        for token in [text, *re.split(r"[^A-Za-z0-9]+", text)]:
            token = token.strip()
            if not token:
                continue
            lower_key = token.lower()
            if lower_key in seen:
                continue
            seen.add(lower_key)
            expanded.append(token)
    return expanded


def build_search_text(
    *,
    display_name: str,
    sku: str,
    object_id: str | None,
    description: str | None,
    legacy_skus: List[str],
    synonyms: List[str],
    attributes: Dict[str, Any],
    attribute_columns: List[str] = DEFAULT_ATTRIBUTE_COLUMNS,
) -> str:
    parts: List[Any] = [
        display_name,
        sku,
        object_id,
        description,
        *legacy_skus,
        *synonyms,
    ]
    for key in attribute_columns:
        value = attributes.get(key)
        if value is None:
            continue
        parts.append(value)
    expanded = expand_search_terms(parts)
    return normalize_search_text(" ".join(expanded))
