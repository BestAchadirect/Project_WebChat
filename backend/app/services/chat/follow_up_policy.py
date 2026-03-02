from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.chat import ProductCard


def normalize_text(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def keyword_tokens(*, text: str, stopwords: set[str]) -> set[str]:
    if not text:
        return set()
    lowered = str(text).lower()
    lowered = lowered.replace("in-stock", "instock").replace("in stock", "instock")
    parts = re.findall(r"[a-z0-9]+", lowered)
    return {
        token
        for token in parts
        if len(token) >= 3 and token not in stopwords
    }


def is_follow_up_relevant(
    *,
    question: str,
    user_text: str,
    route: str,
    has_products: bool,
    use_products: bool,
    use_knowledge: bool,
    is_policy_intent: bool,
    stopwords: set[str],
    product_terms: set[str],
    policy_terms: set[str],
) -> bool:
    if not question:
        return False

    route_norm = str(route or "").strip().lower()
    if route_norm == "fallback_general":
        return False
    if route_norm == "detail_mode":
        return True

    question_tokens = keyword_tokens(text=question, stopwords=stopwords)
    user_tokens = keyword_tokens(text=user_text, stopwords=stopwords)
    if not question_tokens:
        return False

    if question_tokens & user_tokens:
        return True

    question_lower = str(question).strip().lower()
    has_product_signal = bool(question_tokens & product_terms)
    has_policy_signal = bool(question_tokens & policy_terms)

    if has_products and (question_lower.startswith("see more ") or question_lower.startswith("show ")):
        return True

    user_has_product_signal = bool(user_tokens & product_terms)
    if use_products and has_product_signal and (has_products or user_has_product_signal):
        return True

    user_has_policy_signal = bool(user_tokens & policy_terms)
    if use_knowledge and has_policy_signal and (is_policy_intent or user_has_policy_signal):
        return True

    return False


def filter_follow_up_questions(
    *,
    questions: List[str],
    user_text: str,
    route: str,
    has_products: bool,
    retrieval_gate: Optional[Dict[str, Any]],
    stopwords: set[str],
    product_terms: set[str],
    policy_terms: set[str],
    limit: int = 5,
) -> List[str]:
    if not questions:
        return []

    gate = retrieval_gate if isinstance(retrieval_gate, dict) else {}
    use_products = bool(gate.get("use_products", has_products))
    use_knowledge = bool(gate.get("use_knowledge", not use_products))
    is_policy_intent = bool(gate.get("is_policy_intent", False))

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

    kept: List[str] = []
    for question in deduped:
        if is_follow_up_relevant(
            question=question,
            user_text=user_text,
            route=route,
            has_products=has_products,
            use_products=use_products,
            use_knowledge=use_knowledge,
            is_policy_intent=is_policy_intent,
            stopwords=stopwords,
            product_terms=product_terms,
            policy_terms=policy_terms,
        ):
            kept.append(question)
        if len(kept) >= max(1, int(limit)):
            break
    return kept


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
    stopwords: set[str],
    product_terms: set[str],
) -> bool:
    if any(str(v or "").strip() for v in dict(attribute_filters or {}).values()):
        return True
    user_tokens = keyword_tokens(text=user_text, stopwords=stopwords)
    generic_terms = {"browse", "detail", "details", "product", "products", "see", "show", "similar"}
    specific_terms = set(product_terms) - generic_terms
    return bool(user_tokens & specific_terms)


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
        "color": ("color", "cz_color"),
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
    stopwords: set[str],
    product_terms: set[str],
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
        stopwords=stopwords,
        product_terms=product_terms,
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
