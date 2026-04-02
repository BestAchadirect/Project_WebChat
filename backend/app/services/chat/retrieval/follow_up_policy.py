from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.chat import ProductCard
import app.services.chat.presentation.product_presentation as product_presentation


def normalize_text(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def is_follow_up_relevant(
    *,
    question: str,
    user_text: str,
    route: str,
    has_products: bool,
    use_products: bool,
    use_knowledge: bool,
    is_policy_like: bool,
) -> bool:
    if not question:
        return False

    route_norm = str(route or "").strip().lower()
    if route_norm in {"fallback", "fallback_general"}:
        return False
    return False


def filter_follow_up_questions(
    *,
    questions: List[str],
    user_text: str,
    route: str,
    has_products: bool,
    retrieval_gate: Optional[Dict[str, Any]],
    limit: int = 5,
) -> List[str]:
    if not questions:
        return []

    gate = retrieval_gate if isinstance(retrieval_gate, dict) else {}
    use_products = bool(gate.get("use_products", has_products))
    use_knowledge = bool(gate.get("use_knowledge", not use_products))
    is_policy_like = bool(gate.get("is_policy_like", False))

    deduped: List[str] = []
    seen: set[str] = set()
    for raw in questions:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)

    if str(route or "").strip().lower() in {"fallback", "fallback_general"}:
        return []
    return deduped[: max(1, int(limit))]


def normalize_follow_up_attr_value(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return ""
    if len(text) > 40:
        return ""
    return text


def has_product_context(
    *,
    attribute_filters: Dict[str, str],
    user_text: str,
) -> bool:
    if any(str(v or "").strip() for v in dict(attribute_filters or {}).values()):
        return True
    return bool(str(user_text or "").strip())


def extract_product_attribute_values(
    *,
    products: List[ProductCard],
    key: str,
    limit: int = 3,
) -> List[str]:
    aliases: Dict[str, Tuple[str, ...]] = {
        "jewelry_type": ("jewelry_type", "type"),
        "material": ("material",),
        "gauge": ("gauge", "size"),
        "color": ("color", "cz_color", "opal_color", "crystal_color", "pearl_color"),
        "threading": ("threading",),
    }
    alias_keys = aliases.get(key, (key,))
    values: List[str] = []
    seen: set[str] = set()
    cap = max(1, int(limit or 1))
    for product in list(products or []):
        attrs = dict(product.attributes or {})
        raw_value: Any = None
        for alias in alias_keys:
            candidate = attrs.get(alias)
            if candidate not in (None, ""):
                raw_value = candidate
                break
        normalized = normalize_follow_up_attr_value(raw_value)
        if not normalized:
            continue
        token = normalized.lower()
        if token in seen:
            continue
        seen.add(token)
        values.append(normalized)
        if len(values) >= cap:
            break
    return values


def build_product_follow_up_questions(
    *,
    products: List[ProductCard],
    attribute_filters: Dict[str, str],
    user_text: str,
    has_more_results: bool = False,
    limit: int = 4,
) -> List[str]:
    cap = max(1, int(limit or 1))
    if not products:
        return []

    context = {
        "jewelry_type": normalize_follow_up_attr_value(attribute_filters.get("jewelry_type")),
        "material": normalize_follow_up_attr_value(attribute_filters.get("material")),
        "gauge": normalize_follow_up_attr_value(attribute_filters.get("gauge")),
        "color": normalize_follow_up_attr_value(attribute_filters.get("color")),
        "threading": normalize_follow_up_attr_value(attribute_filters.get("threading")),
    }
    has_context = has_product_context(
        attribute_filters=attribute_filters,
        user_text=user_text,
    )

    questions: List[str] = []
    seen: set[str] = set()

    def _add(question: str) -> None:
        text = str(question or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        questions.append(text)

    if has_more_results:
        _add(
            product_presentation.build_see_more_follow_up(
                attribute_filters=attribute_filters,
                user_text=user_text,
            )
        )

    if has_context:
        jewelry_type = context["jewelry_type"]
        material = context["material"]
        gauge = context["gauge"]
        color = context["color"]
        threading = context["threading"]

        if jewelry_type and material and gauge:
            _add(f"Show more {material} {jewelry_type} in {gauge}")
        if jewelry_type and material:
            _add(f"Show more {material} {jewelry_type}")
        if jewelry_type and gauge:
            _add(f"Show more {jewelry_type} in {gauge}")
        if jewelry_type and color:
            _add(f"Show {color} {jewelry_type} options")
        if jewelry_type and threading:
            _add(f"Show {threading} threading {jewelry_type}")
        if material and not jewelry_type:
            _add(f"Show more {material} products")
        if gauge and not jewelry_type:
            _add(f"Show more {gauge} products")

        alt_materials = extract_product_attribute_values(products=products, key="material", limit=3)
        alt_gauges = extract_product_attribute_values(products=products, key="gauge", limit=3)
        for alt in alt_materials:
            if material and alt.lower() == material.lower():
                continue
            if jewelry_type:
                _add(f"Show {alt} {jewelry_type} options")
            else:
                _add(f"Show products in {alt}")
        for alt in alt_gauges:
            if gauge and alt.lower() == gauge.lower():
                continue
            if jewelry_type:
                _add(f"Show {jewelry_type} in {alt}")
            else:
                _add(f"Show {alt} products")
    else:
        jewelry_types = extract_product_attribute_values(products=products, key="jewelry_type", limit=2)
        materials = extract_product_attribute_values(products=products, key="material", limit=2)
        gauges = extract_product_attribute_values(products=products, key="gauge", limit=2)
        colors = extract_product_attribute_values(products=products, key="color", limit=2)

        if jewelry_types and materials:
            _add(f"Show {materials[0]} {jewelry_types[0]} options")
        for jt in jewelry_types:
            _add(f"Show more {jt} options")
        for material in materials:
            _add(f"Show products in {material}")
        for gauge in gauges:
            _add(f"Show {gauge} options")
        for color in colors:
            _add(f"Show {color} color options")

    if not questions:
        _add("Show popular products")

    return questions[:cap]
