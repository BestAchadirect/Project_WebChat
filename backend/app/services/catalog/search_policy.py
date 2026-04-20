from __future__ import annotations

from typing import Mapping, Sequence

from app.core.config import settings
from app.utils.synonym_rules import (
    JEWELRY_TYPE_FALLBACK_TOKENS,
    MATERIAL_FALLBACK_TOKENS,
)

DEFAULT_EAV_PARTIAL_MATCH_KEYS = frozenset(
    {
        "body_part",
        "category",
        "color",
        "crystal_color",
        "cz_color",
        "feature",
        "design",
        "finish",
        "jewelry_type",
        "material",
        "opal_color",
        "packing_option",
        "pearl_color",
        "presentation_type",
        "rack",
        "theme",
        "threading",
    }
)

def catalog_eav_partial_match_keys(raw_value: str | None = None) -> frozenset[str]:
    raw = raw_value if raw_value is not None else getattr(settings, "CATALOG_EAV_PARTIAL_MATCH_KEYS", "")
    parsed = {
        str(item or "").strip().lower()
        for item in str(raw or "").split(",")
        if str(item or "").strip()
    }
    return frozenset(parsed) or DEFAULT_EAV_PARTIAL_MATCH_KEYS


def uses_eav_partial_match(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return bool(normalized) and normalized in catalog_eav_partial_match_keys()
