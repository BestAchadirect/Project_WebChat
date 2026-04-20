from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


CATALOG_FAMILY_SYNONYMS: Dict[str, Dict[str, str]] = {
    "material": {
        "titanium g23": "Titanium G23",
        "g23": "Titanium G23",
        "implant grade": "Titanium G23",
        "implant-grade": "Titanium G23",
        "implant": "Titanium G23",
        "titanium": "Titanium",
        "surgical steel": "Steel",
        "stainless steel": "Steel",
        "316l steel": "Steel",
        "316l": "Steel",
        "steel": "Steel",
        "gold": "Gold",
        "14k gold": "Gold",
        "18k gold": "Gold",
        "silver": "Silver",
        "sterling silver": "Silver",
        "acrylic": "Acrylic",
        "925 silver": "925 Silver",
        "925 sterling silver": "925 Silver",
        "bioflex / ptfe": "Bioflex / PTFE",
        "bioflex": "Bioflex / PTFE",
        "ptfe": "Bioflex / PTFE",
        "pvd plated surgical steel": "PVD Plated Surgical Steel",
        "pvd plated titanium g23": "PVD Plated Titanium G23",
        "rubber": "Rubber",
        "silicone": "Silicone",
        "stainless steel": "Stainless Steel",
        "surgical steel": "Surgical Steel",
        "surgical steel & acrylic attachments": "Surgical Steel & Acrylic Attachments",
        "titanium g23 & acrylic attachments": "Titanium G23 & Acrylic Attachments",
        "titanium g5": "Titanium G5",
        "wood, bone, horn & stones": "Wood, Bone, Horn & Stones",
    },
    "jewelry_type": {
        "labret stud": "Labret",
        "labrets": "Labret",
        "labret": "Labret",
        "circular barbell": "Circular Barbell",
        "barbells": "Barbell",
        "barbell": "Barbell",
        "rings": "Ring",
        "ring": "Ring",
        "studs": "Stud",
        "stud": "Stud",
        "tunnels": "Tunnel",
        "tunnel": "Tunnel",
        "plugs": "Plug",
        "plug": "Plug",
    },
    "threading": {
        "internally threaded": "Internal",
        "internal": "Internal",
        "externally threaded": "External",
        "external": "External",
        "threadless": "Threadless",
    },
    "presentation_type": {
        "sterilized": "Sterilized",
        "sterilised": "Sterilized",
        "sold per piece": "Sold per Piece",
        "sold by piece": "Sold per Piece",
        "sold by pair": "Sold by Pair",
        "sold in bulk": "Sold in Bulk",
        "sold on display": "Sold on Display",
        "sold by pack": "Sold by Pack",
    },
    "body_part": {
        "belly piercing": "Belly Piercing",
        "belly": "Belly Piercing",
        "ear - lobe piercing": "Ear - Lobe Piercing",
        "ear lobe piercing": "Ear - Lobe Piercing",
        "ear lobe": "Ear - Lobe Piercing",
        "ear - other piercing": "Ear - Other Piercing",
        "ear other piercing": "Ear - Other Piercing",
        "eyebrow piercing": "Eyebrow Piercing",
        "helix piercing": "Helix Piercing",
        "intimate piercing": "Intimate Piercing",
        "lower lip piercing": "Lower Lip Piercing",
        "nipple piercing": "Nipple Piercing",
        "nose bridge piercing": "Nose Bridge Piercing",
        "nose piercing": "Nose Piercing",
        "nose": "Nose Piercing",
        "septum piercing": "Septum Piercing",
        "surface piercing": "Surface Piercing",
        "tongue piercing": "Tongue Piercing",
        "tragus piercing": "Tragus Piercing",
        "upper lip / monroe": "Upper Lip / Monroe",
        "upper lip monroe": "Upper Lip / Monroe",
        "upper lip": "Upper Lip / Monroe",
        "monroe": "Upper Lip / Monroe",
    },
    "theme": {
        "checkers": "Checkers",
        "cherries": "Cherries",
        "crosses": "Crosses",
        "dice": "Dice",
        "flowers": "Flowers",
        "gay & lesbian pride": "Gay & Lesbian Pride",
        "gay lesbian pride": "Gay & Lesbian Pride",
        "hearts": "Hearts",
        "lizards": "Lizards",
        "marijuana / mushrooms": "Marijuana / Mushrooms",
        "marijuana mushrooms": "Marijuana / Mushrooms",
        "opal": "Opal",
        "skulls": "Skulls",
        "spider": "Spider",
        "snake eyes": "Snake Eyes",
    },
    "feature": {
        "internally threaded": "Internally Threaded",
        "threadless": "Threadless",
        "pvd plated": "PVD Plated",
        "ferido glued": "Ferido Glued",
        "piercing kits": "Piercing Kits",
        "big gauge": "Big Gauge",
    },
}


ATTRIBUTE_LIST_QUERY_SYNONYMS: Dict[str, str] = {
    "body part": "body_part",
    "body parts": "body_part",
    "feature": "feature",
    "features": "feature",
    "body jewelry type": "jewelry_type",
    "body jewelry types": "jewelry_type",
    "jewelry type": "jewelry_type",
    "jewelry types": "jewelry_type",
    "material": "material",
    "materials": "material",
    "presentation type": "presentation_type",
    "presentation types": "presentation_type",
    "color": "color",
    "colors": "color",
    "gauge": "gauge",
    "gauges": "gauge",
    "threading": "threading",
    "threadings": "threading",
    "theme": "theme",
    "themes": "theme",
    "type": "jewelry_type",
    "types": "jewelry_type",
}

BODY_PART_SUITABILITY_AMBIGUOUS_MODIFIERS = frozenset(
    {
        "fake",
        "false",
        "mock",
        "prosthetic",
        "replica",
        "simulated",
        "dummy",
    }
)

BODY_PART_SUITABILITY_TERMS = frozenset(
    {
        "belly",
        "ear",
        "eyebrow",
        "helix",
        "intimate",
        "lip",
        "monroe",
        "nipple",
        "nose",
        "septum",
        "surface",
        "tongue",
        "tragus",
    }
)

ATTRIBUTE_LIST_TARGETS = frozenset(ATTRIBUTE_LIST_QUERY_SYNONYMS.values())
DEFAULT_SOFT_ATTRIBUTE_KEYS = frozenset(
    {
        "category",
        "color",
        "crystal_color",
        "design",
        "finish",
        "jewelry_type",
        "material",
        "opal_color",
        "pearl_color",
        "theme",
        "stone",
        "threading",
    }
)

ATTRIBUTE_CONFLICT_PRIORITIES: Dict[str, tuple[str, ...]] = {
    "color": ("opal_color",),
    "size": ("ring_size", "size_in_pack", "pincher_size"),
}


def normalize_family_value(*, family: str, value: Any) -> str:
    clean_family = _normalize_text(family)
    original = str(value or "").strip()
    text = _normalize_text(value)
    if not clean_family or not text:
        return ""
    family_map = CATALOG_FAMILY_SYNONYMS.get(clean_family)
    if not family_map:
        return original or text
    for token in sorted(family_map.keys(), key=len, reverse=True):
        if token and token in text:
            return family_map[token]
    return original or text


def normalize_design_family_value(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    text = re.sub(
        r"^(?:see|show|find|get|can i see|can you see|i want|looking for|look for)\s+",
        "",
        text,
    )
    if " with " in text:
        text = text.split(" with ")[-1].strip()
    text = re.sub(r"^(?:a|an|the)\s+", "", text)
    text = re.sub(r"\bshape\b$", "", text).strip()
    return re.sub(r"\s+", " ", text).strip()


def normalize_attribute_list_target(raw_target: Any) -> str:
    target = _normalize_text(raw_target)
    if not target:
        return ""
    target = ATTRIBUTE_LIST_QUERY_SYNONYMS.get(target, target)
    if target in ATTRIBUTE_LIST_TARGETS:
        return target
    target = target.replace(" ", "_")
    return target if target in ATTRIBUTE_LIST_TARGETS else ""


def resolve_attribute_conflicts(attribute_filters: Mapping[str, Any] | None) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in dict(attribute_filters or {}).items():
        clean_key = _normalize_text(key)
        if not clean_key:
            continue
        clean[clean_key] = value

    for primary_key, conflicting_keys in ATTRIBUTE_CONFLICT_PRIORITIES.items():
        if primary_key not in clean:
            continue
        primary_value = clean.get(primary_key)
        for conflicting_key in conflicting_keys:
            conflicting_value = clean.get(conflicting_key)
            if conflicting_value is not None and conflicting_value == primary_value:
                clean.pop(primary_key, None)
                break
    return clean


def build_search_synonyms_map() -> Dict[str, List[str]]:
    synonyms: Dict[str, List[str]] = {}
    for family_map in CATALOG_FAMILY_SYNONYMS.values():
        for raw_value, canonical_value in family_map.items():
            raw_norm = _normalize_text(raw_value)
            canonical_norm = _normalize_text(canonical_value)
            if not raw_norm or not canonical_norm or raw_norm == canonical_norm:
                continue
            bucket = synonyms.setdefault(canonical_norm, [])
            if raw_norm not in bucket:
                bucket.append(raw_norm)
    return synonyms


def build_fallback_tokens_map(*, family: str) -> Dict[str, Sequence[str]]:
    clean_family = _normalize_text(family)
    family_map = CATALOG_FAMILY_SYNONYMS.get(clean_family, {})
    buckets: Dict[str, List[str]] = {}
    for raw_value, canonical_value in family_map.items():
        canonical = str(canonical_value or "").strip()
        raw_norm = _normalize_text(raw_value)
        canonical_norm = _normalize_text(canonical_value)
        if not canonical or not canonical_norm:
            continue
        bucket = buckets.setdefault(canonical, [])
        if canonical_norm not in bucket:
            bucket.append(canonical_norm)
        if raw_norm and raw_norm != canonical_norm and raw_norm not in bucket:
            bucket.append(raw_norm)
    return {key: tuple(values) for key, values in buckets.items()}


SEARCH_SYNONYMS: Dict[str, List[str]] = build_search_synonyms_map()
MATERIAL_FALLBACK_TOKENS: Dict[str, Sequence[str]] = build_fallback_tokens_map(family="material")
JEWELRY_TYPE_FALLBACK_TOKENS: Dict[str, Sequence[str]] = build_fallback_tokens_map(family="jewelry_type")
THREADING_FALLBACK_TOKENS: Dict[str, Sequence[str]] = build_fallback_tokens_map(family="threading")
PRESENTATION_TYPE_FALLBACK_TOKENS: Dict[str, Sequence[str]] = build_fallback_tokens_map(family="presentation_type")
BODY_PART_FALLBACK_TOKENS: Dict[str, Sequence[str]] = build_fallback_tokens_map(family="body_part")
THEME_FALLBACK_TOKENS: Dict[str, Sequence[str]] = build_fallback_tokens_map(family="theme")
FEATURE_FALLBACK_TOKENS: Dict[str, Sequence[str]] = build_fallback_tokens_map(family="feature")
