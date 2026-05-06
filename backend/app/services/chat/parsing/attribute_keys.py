from __future__ import annotations

from typing import Any


ATTRIBUTE_KEY_ALIASES = {
    "body part": "body_location",
    "body parts": "body_location",
    "body_part": "body_location",
    "body location": "body_location",
    "body locations": "body_location",
    "diameter": "outer_diameter",
    "type": "jewelry_type",
    "types": "jewelry_type",
}


def canonicalize_filter_key(key: Any) -> str:
    clean_key = str(key or "").strip().lower()
    if not clean_key:
        return ""
    clean_key = clean_key.replace("-", "_")
    return ATTRIBUTE_KEY_ALIASES.get(clean_key, clean_key)
