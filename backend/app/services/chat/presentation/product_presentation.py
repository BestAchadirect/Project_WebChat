from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from app.services.chat.components.builders.contextual_messages import generate_contextual_reply

PRODUCT_DISPLAY_LIMIT = 10
_MISSING_MATERIAL_TERMS = ("anodized", "anodised")
ATTRIBUTE_DISPLAY_ORDER = (
    "category",
    "presentation_type",
    "body_part",
    "theme",
    "feature",
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
        elif key == "presentation_type":
            parts.append(f"{text}")
        elif key == "body_part":
            parts.append(f"for {text}")
        elif key == "theme":
            parts.append(f"with {text} theme")
        elif key == "feature":
            parts.append(f"with {text}")
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


def _build_deterministic_product_reply(
    *,
    attribute_filters: Dict[str, str],
    user_text: str,
    products: Sequence[Any] | None = None,
    requested_fields: Sequence[str] | None = None,
    result_count: int | None = None,
) -> str:
    phrase = build_attribute_match_phrase(attribute_filters)
    product_list = list(products or [])
    if _looks_like_missing_material_request(user_text=user_text, products=product_list):
        if product_list:
            return "We don't currently have anodized products in the store. Here are some related options you might like."
        return "We don't currently have anodized products in the store."
    if product_list:
        focus_label = _product_focus_label(products=product_list, attribute_filters=attribute_filters)
        benefit_text = _product_benefit_text(products=product_list, attribute_filters=attribute_filters)
        requested = {
            str(item or "").strip().lower()
            for item in list(requested_fields or [])
            if str(item or "").strip()
        }
        count = int(result_count or len(product_list) or 0)
        count_text = f"{count} " if count > 0 else ""
        if requested.intersection({"price", "stock"}):
            detail_bits: List[str] = []
            if "price" in requested:
                detail_bits.append("prices")
            if "stock" in requested:
                detail_bits.append("stock status")
            details = " and ".join(detail_bits)
            verb = "are" if len(detail_bits) > 1 or "price" in requested else "is"
            scope = focus_label or "matching products"
            return f"I found {count_text}{scope}. {details.capitalize()} {verb} shown on each item below."
        base = "I found products that match your request"
        if phrase:
            base = f"{base} {phrase}"
        elif focus_label:
            base = f"{base} for {focus_label}"
        else:
            base = f"{base}."
        if benefit_text:
            return f"{base}. These options are {benefit_text}."
        return base if base.endswith(".") else f"{base}."
    if phrase:
        return f"I found products that match what you're looking for {phrase}."
    if user_text:
        return "I found products that match what you're looking for."
    return "I found products that match what you're looking for."


async def build_product_match_reply(
    *,
    attribute_filters: Dict[str, str],
    user_text: str = "",
    products: Sequence[Any] | None = None,
    locale: str = "en-US",
    use_llm: bool = True,
    requested_fields: Sequence[str] | None = None,
    result_count: int | None = None,
) -> str:
    product_list = list(products or [])
    if _looks_like_missing_material_request(user_text=user_text, products=product_list):
        if product_list:
            return "We don't currently have anodized products in the store. Here are some related options you might like."
        return "We don't currently have anodized products in the store."
    if not use_llm:
        return _build_deterministic_product_reply(
            attribute_filters=attribute_filters,
            user_text=user_text,
            products=product_list,
            requested_fields=requested_fields,
            result_count=result_count,
        )

    phrase = build_attribute_match_phrase(attribute_filters)
    if product_list:
        focus_label = _product_focus_label(products=product_list, attribute_filters=attribute_filters)
        benefit_text = _product_benefit_text(products=product_list, attribute_filters=attribute_filters)
        reply = await generate_contextual_reply(
            kind="product",
            reply_language=locale,
            payload={
                "user_text": user_text or focus_label,
                "query_summary": user_text or focus_label,
                "phrase": phrase,
                "focus_label": focus_label,
                "benefit_text": benefit_text,
                "products": [
                    {
                        "title": _display_text(getattr(product, "title", "")),
                        "sku": _display_text(getattr(product, "sku", "")),
                        "material": _display_text(dict(getattr(product, "attributes", {}) or {}).get("material")),
                        "jewelry_type": _display_text(dict(getattr(product, "attributes", {}) or {}).get("jewelry_type")),
                    }
                    for product in product_list[:3]
                ],
            },
        )
        if reply:
            return reply
        if phrase:
            return f"I found products that match what you're looking for {phrase}."
        return "I found products that match what you're looking for."
    if not user_text:
        if phrase:
            return f"I found products that match what you're looking for {phrase}."
        return "I found products that match what you're looking for."
    reply = await generate_contextual_reply(
        kind="product",
        reply_language=locale,
        payload={
            "user_text": user_text,
            "query_summary": user_text,
            "phrase": phrase,
            "focus_label": "",
            "benefit_text": "",
            "products": [],
        },
    )
    if reply:
        return reply
    if phrase:
        return f"I found products that match what you're looking for {phrase}."
    return "I found products that match what you're looking for."


def build_compare_product_reply(
    *,
    products: Sequence[Any],
    user_text: str = "",
) -> str:
    product_list = [product for product in list(products or []) if product is not None]
    if not product_list:
        return "I couldn't find enough products to compare."

    lines: List[str] = []
    count = len(product_list)
    lines.append(f"I found {count} products to compare.")
    for product in product_list[:5]:
        master_code = _display_text(master_code_from_product(product)) or _display_text(getattr(product, "sku", ""))
        price = getattr(product, "price", None)
        currency = _display_text(getattr(product, "currency", "")) or "USD"
        stock_status = "in stock" if bool(getattr(product, "in_stock", False)) else "out of stock"
        attrs = dict(getattr(product, "attributes", {}) or {})
        parts: List[str] = []
        for key in ("material", "jewelry_type", "gauge", "color", "length"):
            value = _display_text(attrs.get(key))
            if value:
                parts.append(value)
        detail_bits: List[str] = []
        if price is not None:
            try:
                detail_bits.append(f"{float(price):.2f} {currency}")
            except Exception:
                detail_bits.append(f"{price} {currency}")
        detail_bits.append(stock_status)
        if parts:
            detail_bits.append(", ".join(parts[:3]))
        line = f"- {master_code}: " + ", ".join(detail_bits)
        lines.append(line)

    if user_text:
        lines.append("Open a card to compare the full details side by side.")
    return "\n".join(lines)


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


def _looks_like_missing_material_request(*, user_text: str, products: Sequence[Any]) -> bool:
    text = _display_text(user_text).lower()
    if not text or not any(term in text for term in _MISSING_MATERIAL_TERMS):
        return False

    product_list = list(products or [])
    searchable_terms = " ".join(
        [
            *(_product_attribute_values(product_list, "material", limit=6)),
            *(_product_attribute_values(product_list, "category", limit=6)),
        ]
    ).lower()
    return not any(term in searchable_terms for term in _MISSING_MATERIAL_TERMS)


def build_see_more_follow_up(*, attribute_filters: Dict[str, str], user_text: str) -> str:
    # Quick-reply UX is currently disabled, so we intentionally suppress this CTA.
    return ""
