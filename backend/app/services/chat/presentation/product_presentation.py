from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

import app.services.chat.presentation.reply_tone as reply_tone

PRODUCT_DISPLAY_LIMIT = 10
ATTRIBUTE_DISPLAY_ORDER = (
    "category",
    "jewelry_type",
    "design",
    "color",
    "material",
    "opal_color",
    "pearl_color",
    "crystal_color",
    "cz_color",
    "gauge",
    "length",
    "size",
    "outer_diameter",
    "ring_size",
    "height",
    "threading",
    "packing_option",
    "size_in_pack",
    "quantity_in_bulk",
    "pincher_size",
    "rack",
)


def _display_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace(";;", " / ")
    if not text:
        return ""
    if text.islower():
        return " ".join(part.capitalize() for part in text.split(" ") if part)
    return text


def master_code_from_product(product: Any) -> str:
    attrs = dict(getattr(product, "attributes", {}) or {})
    candidates = (
        attrs.get("master_code"),
        getattr(product, "title", None),
        getattr(product, "name", None),
        getattr(product, "sku", None),
        getattr(product, "product_id", None),
        getattr(product, "id", None),
    )
    for raw in candidates:
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def dedupe_products_by_master_code(
    products: Sequence[Any],
    *,
    limit: int = PRODUCT_DISPLAY_LIMIT,
) -> Tuple[List[Any], int]:
    deduped: List[Any] = []
    seen: set[str] = set()
    for product in list(products or []):
        master_code = master_code_from_product(product)
        key = master_code.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if len(deduped) < max(1, int(limit or PRODUCT_DISPLAY_LIMIT)):
            deduped.append(product)
    return deduped, len(seen)


def build_attribute_match_phrase(attribute_filters: Dict[str, str]) -> str:
    filters = dict(attribute_filters or {})
    parts: List[str] = []
    for key in ATTRIBUTE_DISPLAY_ORDER:
        text = _display_text(filters.get(key))
        if not text:
            continue
        if key == "category":
            parts.append(f"in {text}")
        elif key == "jewelry_type":
            parts.append(f"for {text}")
        elif key == "design":
            parts.append(f"with {text} design")
        elif key == "color":
            parts.append(f"in {text} color")
        elif key == "material":
            parts.append(f"with {text} material")
        elif key == "opal_color":
            parts.append(f"with {text} opal color")
        elif key == "pearl_color":
            parts.append(f"with {text} pearl color")
        elif key == "crystal_color":
            parts.append(f"with {text} crystal color")
        elif key == "cz_color":
            parts.append(f"with {text} CZ color")
        elif key == "gauge":
            parts.append(f"in {text}")
        elif key == "length":
            parts.append(f"with {text} length")
        elif key == "size":
            parts.append(f"in size {text}")
        elif key == "outer_diameter":
            parts.append(f"with {text} outer diameter")
        elif key == "ring_size":
            parts.append(f"in ring size {text}")
        elif key == "height":
            parts.append(f"with {text} height")
        elif key == "threading":
            parts.append(f"with {text} threading")
        elif key == "packing_option":
            parts.append(f"with {text} packing option")
        elif key == "size_in_pack":
            parts.append(f"with pack size {text}")
        elif key == "quantity_in_bulk":
            parts.append(f"with bulk quantity {text}")
        elif key == "pincher_size":
            parts.append(f"in pincher size {text}")
        elif key == "rack":
            parts.append(f"in rack {text}")
    return " ".join(parts).strip()


def build_product_match_reply(*, attribute_filters: Dict[str, str], user_text: str = "") -> str:
    phrase = build_attribute_match_phrase(attribute_filters)
    if not user_text:
        if phrase:
            return f"I found products that match what you're looking for {phrase}."
        return "I found products that match what you're looking for."
    if phrase:
        return reply_tone.pick_variant(
            user_text=user_text,
            key=f"product_match:{phrase}",
            variants=[
                f"I found products that match your request {phrase}.",
                f"Good choice. I found matching options {phrase}.",
                f"Nice, these products match your request {phrase}.",
            ],
        )
    return reply_tone.pick_variant(
        user_text=user_text,
        key="product_match:generic",
        variants=[
            "I found products that match what you're looking for.",
            "I found matching products for you.",
            "I found a few options that fit your request.",
        ],
    )


def build_recommendation_match_reply(*, attribute_filters: Dict[str, str], user_text: str = "") -> str:
    phrase = build_attribute_match_phrase(attribute_filters)
    if not user_text:
        if phrase:
            return f"I found some recommended options {phrase}."
        return "I found some recommended options that match what you're looking for."
    if phrase:
        return reply_tone.pick_variant(
            user_text=user_text,
            key=f"recommendation_match:{phrase}",
            variants=[
                f"I found recommendations that match your request {phrase}.",
                f"Great, here are recommendations {phrase}.",
                f"These recommendations should fit what you asked for {phrase}.",
            ],
        )
    return reply_tone.pick_variant(
        user_text=user_text,
        key="recommendation_match:generic",
        variants=[
            "I found some recommended options that match what you're looking for.",
            "Here are recommendations based on what you asked for.",
            "I found a few recommendations you might like.",
        ],
    )


def build_see_more_follow_up(*, attribute_filters: Dict[str, str], user_text: str) -> str:
    # Quick-reply UX is currently disabled, so we intentionally suppress this CTA.
    return ""
