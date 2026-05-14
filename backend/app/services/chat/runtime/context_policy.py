from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional

from app.services.chat.text_normalization import normalize_user_text

ACTIVE_PRODUCT_TTL_SECONDS = 20 * 60
ATTRIBUTE_FILTER_TTL_SECONDS = 30 * 60

PAGINATION_MARKERS = {
    "show more",
    "see more",
    "more products",
    "next",
    "next page",
    "more",
}

RESET_MARKERS = {
    "different topic",
    "new search",
    "forget that",
    "forget it",
    "start over",
}

PRODUCT_DETAIL_FIELD_TERMS = {
    "price": ("price", "cost", "how much", "cheaper", "cheapest"),
    "stock": ("stock", "available", "availability", "in stock", "order this", "can i order"),
    "attributes": ("details", "tell me about", "what size", "what material", "where is it made", "made in", "origin"),
    "image": ("photo", "picture", "image"),
}

MATERIAL_TERMS = (
    ("surgical steel", "surgical steel"),
    ("stainless steel", "stainless steel"),
    ("rose gold", "rose gold"),
    ("titanium", "titanium"),
    ("silicone", "silicone"),
    ("acrylic", "acrylic"),
    ("bioplast", "bioplast"),
    ("glass", "glass"),
    ("steel", "steel"),
    ("gold", "gold"),
)

JEWELRY_TYPE_TERMS = (
    ("nose rings", "nose ring"),
    ("nose ring", "nose ring"),
    ("nostril hoop", "nose ring"),
    ("nose hoop", "nose ring"),
    ("labrets", "labret"),
    ("labret", "labret"),
    ("belly rings", "navel ring"),
    ("belly ring", "navel ring"),
    ("navel rings", "navel ring"),
    ("navel ring", "navel ring"),
    ("septum", "septum"),
    ("barbells", "barbell"),
    ("barbell", "barbell"),
)

PRODUCT_TYPE_SIGNAL_TERMS = (
    "ring",
    "rings",
    "hoop",
    "hoops",
    "stud",
    "studs",
    "screw",
    "screws",
    "labret",
    "labrets",
    "barbell",
    "barbells",
    "banana",
    "bananas",
    "septum",
    "navel",
    "belly",
    "nose",
    "nostril",
    "plug",
    "plugs",
    "tunnel",
    "tunnels",
    "stretcher",
    "stretchers",
)

ORDINALS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
}


def parse_utc(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_timestamp(now: Optional[datetime] = None) -> str:
    value = now or utc_now()
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_expired(value: Any, *, now: Optional[datetime], ttl_seconds: int) -> bool:
    created = parse_utc(value)
    if created is None:
        return False
    current = now or utc_now()
    return (current.astimezone(timezone.utc) - created).total_seconds() > ttl_seconds


def active_product_expired(active_product: Dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    timestamp = active_product.get("updated_at") or active_product.get("created_at")
    return is_expired(timestamp, now=now, ttl_seconds=ACTIVE_PRODUCT_TTL_SECONDS)


def filters_expired(state: Dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    return is_expired(state.get("updated_at"), now=now, ttl_seconds=ATTRIBUTE_FILTER_TTL_SECONDS)


def detects_pagination(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    return normalized in PAGINATION_MARKERS or any(
        normalized.startswith(marker) for marker in ("show more", "see more", "more products", "next")
    )


def detects_reset(text: str) -> str:
    normalized = normalize_user_text(text)
    if not normalized:
        return ""
    for marker in RESET_MARKERS:
        if marker in normalized:
            return marker
    if re.match(r"^(?:now|instead|actually)\s+(?:show|find|search|look for)\b", normalized):
        return "explicit_topic_switch"
    return ""


def detail_fields_from_text(text: str) -> List[str]:
    normalized = normalize_user_text(text)
    fields: List[str] = []
    for field, terms in PRODUCT_DETAIL_FIELD_TERMS.items():
        if any(term in normalized for term in terms):
            fields.append(field)
    return list(dict.fromkeys(fields))


def is_product_sensitive_detail(text: str, requested_fields: Optional[List[str]] = None) -> bool:
    fields = set(detail_fields_from_text(text))
    fields.update(str(item or "").strip().lower() for item in list(requested_fields or []) if str(item or "").strip())
    return bool(fields.intersection({"price", "stock", "attributes", "image"}))


def has_pronoun_product_reference(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    return bool(re.search(r"\b(it|this|that|this one|that one|the item|the product|this product)\b", normalized))


def _term_is_negated(normalized: str, term: str) -> bool:
    escaped = re.escape(term)
    return bool(re.search(rf"\b(?:not|no|without)\s+{escaped}\b", normalized))


def extract_filter_overrides(text: str) -> Dict[str, str]:
    normalized = normalize_user_text(text)
    if not normalized:
        return {}
    filters: Dict[str, str] = {}
    materials: List[str] = []
    for phrase, value in MATERIAL_TERMS:
        if re.search(rf"\b{re.escape(phrase)}\b", normalized) and not _term_is_negated(normalized, phrase):
            materials.append(value)
    if materials:
        filters["material"] = materials[-1]

    length_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(mm|millimeter|millimeters|inch|inches|in)\b", normalized)
    if length_match and ("length" in normalized or normalized.startswith("with ") or normalized.startswith("in ")):
        unit = str(length_match.group(2) or "").lower()
        suffix = "mm" if unit.startswith("m") else "inch"
        filters["length"] = f"{length_match.group(1)}{suffix}"

    gauge_match = re.search(r"\b(\d{1,2})\s*g(?:auge)?\b", normalized)
    if gauge_match:
        filters["gauge"] = f"{gauge_match.group(1)}g"

    for phrase, value in JEWELRY_TYPE_TERMS:
        if re.search(rf"\b{re.escape(phrase)}\b", normalized):
            filters["jewelry_type"] = value
            break
    return filters


def has_explicit_product_type_signal(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    if extract_filter_overrides(normalized).get("jewelry_type"):
        return True
    return any(re.search(rf"\b{re.escape(term)}\b", normalized) for term in PRODUCT_TYPE_SIGNAL_TERMS)


def detect_position_reference(text: str, displayed_products: List[Dict[str, Any]]) -> Optional[int]:
    normalized = normalize_user_text(text)
    if not normalized:
        return None
    if re.search(r"\blast\s+(?:one|item|product)?\b", normalized):
        return len(displayed_products) if displayed_products else None
    for word, position in ORDINALS.items():
        if re.search(rf"\b{re.escape(word)}\s*(?:one|item|product)?\b", normalized):
            return position
    numeric = re.search(r"\b(?:number|#)\s*(\d{1,2})\b", normalized)
    if numeric:
        return int(numeric.group(1))
    details_number = re.search(r"\b(?:details?|product|item)\s*(?:for)?\s*(\d{1,2})\b", normalized)
    if details_number:
        return int(details_number.group(1))
    return None


def topic_switch_reason(*, text: str, previous_filters: Dict[str, str], current_filters: Dict[str, str]) -> str:
    reset_marker = detects_reset(text)
    if reset_marker:
        return reset_marker
    previous_type = normalize_user_text(previous_filters.get("jewelry_type") or "")
    current_type = normalize_user_text(current_filters.get("jewelry_type") or "")
    if previous_type and current_type and previous_type != current_type and has_explicit_product_type_signal(text):
        return "new_product_type"
    previous_category = normalize_user_text(previous_filters.get("category") or "")
    current_category = normalize_user_text(current_filters.get("category") or "")
    if previous_category and current_category and previous_category != current_category and has_explicit_product_type_signal(text):
        return "new_category"
    return ""


def find_displayed_product_by_position(
    displayed_products: List[Dict[str, Any]],
    position: Optional[int],
) -> Dict[str, Any]:
    if not position:
        return {}
    for item in list(displayed_products or []):
        try:
            item_position = int(item.get("position") or 0)
        except Exception:
            item_position = 0
        if item_position == int(position):
            return dict(item)
    return {}


def find_displayed_product_by_descriptor(
    displayed_products: List[Dict[str, Any]],
    text: str,
) -> Dict[str, Any]:
    normalized = normalize_user_text(text)
    if not normalized:
        return {}
    matches: List[Dict[str, Any]] = []
    for item in list(displayed_products or []):
        haystack = normalize_user_text(
            " ".join(
                [
                    str(item.get("sku") or ""),
                    str(item.get("master_code") or ""),
                    str(item.get("name") or ""),
                ]
            )
        )
        if haystack and any(token in haystack for token in normalized.split() if len(token) >= 4):
            matches.append(dict(item))
    return matches[0] if len(matches) == 1 else {}
