from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from app.prompts.response_copy import pick_response_copy
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


def build_product_match_reply(
    *,
    attribute_filters: Dict[str, str],
    user_text: str = "",
    products: Sequence[Any] | None = None,
) -> str:
    phrase = build_attribute_match_phrase(attribute_filters)
    product_list = list(products or [])
    if product_list:
        focus_label = _product_focus_label(products=product_list, attribute_filters=attribute_filters)
        benefit_text = _product_benefit_text(products=product_list, attribute_filters=attribute_filters)
        return pick_response_copy(
            key="product_summary.attribute" if phrase else "product_summary.generic",
            user_text=user_text or focus_label,
            values={
                "focus_label": focus_label,
                "phrase": phrase,
                "benefit_text": benefit_text,
            },
        )
    if not user_text:
        if phrase:
            return f"I found products that match what you're looking for {phrase}."
        return "I found products that match what you're looking for."
    if phrase:
        return pick_response_copy(
            key="product_match.attribute",
            user_text=user_text,
            values={"phrase": phrase},
        )
    return pick_response_copy(
        key="product_match.generic",
        user_text=user_text,
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


def _product_attribute_values(products: Sequence[Any], key: str, limit: int = 3) -> List[str]:
    values: List[str] = []
    seen: set[str] = set()
    for product in list(products or []):
        attrs = dict(getattr(product, "attributes", {}) or {})
        raw_value = attrs.get(key) or getattr(product, key, None)
        text = _display_text(raw_value)
        if not text:
            continue
        token = text.lower()
        if token in seen:
            continue
        seen.add(token)
        values.append(text)
        if len(values) >= max(1, int(limit or 1)):
            break
    return values


def _product_focus_label(*, products: Sequence[Any], attribute_filters: Dict[str, str]) -> str:
    product_list = list(products or [])
    jewelry_types = _product_attribute_values(product_list, "jewelry_type", limit=2)
    materials = _product_attribute_values(product_list, "material", limit=2)
    colors = _product_attribute_values(product_list, "color", limit=1)
    anchor_type = _display_text(attribute_filters.get("jewelry_type"))
    anchor_material = _display_text(attribute_filters.get("material"))
    anchor_color = _display_text(attribute_filters.get("color"))

    material = anchor_material or (materials[0] if materials else "")
    jewelry_type = anchor_type or (jewelry_types[0] if jewelry_types else "")
    color = anchor_color or (colors[0] if colors else "")

    if material and jewelry_type:
        return f"{material.lower()} {jewelry_type.lower()} options"
    if material:
        return f"{material.lower()} options"
    if color and jewelry_type:
        return f"{color.lower()} {jewelry_type.lower()} options"
    if jewelry_type:
        return f"{jewelry_type.lower()} options"
    if color:
        return f"{color.lower()} options"
    return "matching options"


def _product_benefit_text(*, products: Sequence[Any], attribute_filters: Dict[str, str]) -> str:
    product_list = list(products or [])
    materials = [value.lower() for value in _product_attribute_values(product_list, "material", limit=2)]
    colors = [value.lower() for value in _product_attribute_values(product_list, "color", limit=2)]
    jewelry_types = [value.lower() for value in _product_attribute_values(product_list, "jewelry_type", limit=2)]
    attrs = dict(attribute_filters or {})
    material = _display_text(attrs.get("material")).lower() or (materials[0] if materials else "")
    color = _display_text(attrs.get("color")).lower() or (colors[0] if colors else "")
    jewelry_type = _display_text(attrs.get("jewelry_type")).lower() or (jewelry_types[0] if jewelry_types else "")

    if "titanium" in material:
        return "lightweight and skin-friendly"
    if "steel" in material:
        return "durable and versatile"
    if "gold" in material:
        return "polished and easy to style"
    if "black" in color:
        return "clean, bold, and easy to match"
    if any(token in jewelry_type for token in ("top", "attachment", "end")):
        return "easy to mix and match"
    return "a strong everyday choice"


def build_recommendation_summary_reply(
    *,
    products: Sequence[Any],
    attribute_filters: Dict[str, str],
    recommendation_mode: str = "",
    recommendation_label: str = "",
    user_text: str = "",
) -> str:
    del user_text
    product_list = list(products or [])
    if not product_list:
        return "I found a few matching options. What would you like to focus on next: gauge, length, color, or threading?"

    anchor_type = _display_text(attribute_filters.get("jewelry_type"))
    jewelry_types = _product_attribute_values(product_list, "jewelry_type", limit=2)
    materials = _product_attribute_values(product_list, "material", limit=1)
    gauges = _product_attribute_values(product_list, "gauge", limit=1)
    threadings = _product_attribute_values(product_list, "threading", limit=1)

    focus_label = ""
    recommendation_mode = str(recommendation_mode or "").strip().lower()
    recommendation_label = _display_text(recommendation_label)
    if recommendation_mode == "complementary_items" and recommendation_label:
        focus_label = f"compatible {recommendation_label.lower()}"
    if jewelry_types:
        first_type = jewelry_types[0].strip()
        lowered = first_type.lower()
        if not focus_label and any(token in lowered for token in ("top", "end", "ball", "attachment")):
            focus_label = f"compatible {first_type.lower()} options"
        elif not focus_label:
            focus_label = f"{first_type.lower()} options"
    elif anchor_type and not focus_label:
        focus_label = f"matching options for your {anchor_type.lower()}"
    elif not focus_label:
        focus_label = "a few matching options"

    detail_bits: List[str] = []
    if materials:
        detail_bits.append(f"mostly in {materials[0]}")
    if gauges:
        detail_bits.append(f"around {gauges[0]}")
    if threadings:
        detail_bits.append(f"with {threadings[0]} threading")

    summary = pick_response_copy(
        key=(
            "recommendation_summary.complementary"
            if recommendation_mode == "complementary_items" and recommendation_label
            else "recommendation_summary.generic"
        ),
        user_text=str(recommendation_mode or focus_label or anchor_type or "recommendation"),
        values={
            "focus_label": focus_label or "a few matching options",
            "anchor_type": anchor_type.lower() if anchor_type else "",
            "recommendation_label": recommendation_label,
            "benefit_text": _product_benefit_text(products=product_list, attribute_filters=attribute_filters),
        },
        fallback_variants=[
            "I found {focus_label} that are {benefit_text}",
            "Here are {focus_label} that are {benefit_text}",
            "I pulled up {focus_label} that are {benefit_text}",
        ],
    )
    if anchor_type and anchor_type.lower() not in focus_label.lower():
        summary = f"{summary} for your {anchor_type.lower()}"
    if recommendation_mode == "complementary_items" and recommendation_label and recommendation_label.lower() not in summary.lower():
        summary = f"{summary} ({recommendation_label})"
    if detail_bits:
        summary = f"{summary} ({', '.join(detail_bits)})"

    question = "What would you like to focus on next: gauge, length, color, or threading?"
    return f"{summary}. {question}"


def build_see_more_follow_up(*, attribute_filters: Dict[str, str], user_text: str) -> str:
    # Quick-reply UX is currently disabled, so we intentionally suppress this CTA.
    return ""
