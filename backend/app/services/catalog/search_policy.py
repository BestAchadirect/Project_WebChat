from __future__ import annotations

from typing import Mapping, Sequence

from app.core.config import settings

DEFAULT_EAV_PARTIAL_MATCH_KEYS = frozenset(
    {
        "category",
        "color",
        "crystal_color",
        "cz_color",
        "design",
        "finish",
        "jewelry_type",
        "material",
        "opal_color",
        "packing_option",
        "pearl_color",
        "rack",
        "threading",
    }
)

MATERIAL_FALLBACK_TOKENS: Mapping[str, Sequence[str]] = {
    "Titanium G23": ("titanium g23", "g23", "implant grade", "implant-grade", "implant"),
    "Titanium": ("titanium",),
    "Steel": ("surgical steel", "stainless steel", "316l", "steel"),
    "Gold": ("gold",),
    "Silver": ("silver",),
    "Niobium": ("niobium",),
    "Acrylic": ("acrylic",),
}

JEWELRY_TYPE_FALLBACK_TOKENS: Mapping[str, Sequence[str]] = {
    "Barbell": ("barbell", "barbells"),
    "Circular Barbell": ("circular barbell", "horseshoe"),
    "Labret": ("labret", "labrets"),
    "Ring": ("ring", "rings"),
    "Stud": ("stud", "studs"),
    "Tunnel": ("tunnel", "tunnels"),
    "Plug": ("plug", "plugs"),
}


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
