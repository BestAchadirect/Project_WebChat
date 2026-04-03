from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.chat import ProductCard
import app.services.chat.presentation.product_presentation as product_presentation


_FOLLOW_UP_STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "best",
    "can",
    "do",
    "find",
    "for",
    "from",
    "get",
    "give",
    "have",
    "in",
    "is",
    "it",
    "like",
    "more",
    "my",
    "of",
    "on",
    "options",
    "option",
    "product",
    "products",
    "piece",
    "pieces",
    "show",
    "see",
    "tell",
    "the",
    "to",
    "try",
    "what",
    "with",
    "you",
    "your",
    "matching",
    "browse",
    "narrow",
    "filter",
    "focus",
    "jewelry",
}

_PRODUCT_FOLLOW_UP_HINTS = {
    "gauge",
    "size",
    "length",
    "color",
    "material",
    "style",
    "design",
    "threading",
    "threadless",
    "internally",
    "externally",
    "stock",
    "price",
    "sku",
    "titanium",
    "steel",
    "gold",
    "opal",
    "labret",
    "barbell",
    "ring",
    "cartilage",
    "helix",
    "nose",
    "top",
    "end",
    "ball",
    "back",
}

_KNOWLEDGE_FOLLOW_UP_HINTS = {
    "shipping",
    "delivery",
    "refund",
    "return",
    "contact",
    "email",
    "phone",
    "policy",
    "warranty",
    "invoice",
    "payment",
    "store",
    "location",
    "address",
    "sales",
    "support",
}


def normalize_text(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def _tokenize_follow_up(text: str) -> List[str]:
    return [
        token
        for token in normalize_text(text).split()
        if token and token not in _FOLLOW_UP_STOPWORDS
    ]


def _follow_up_signature(question: str) -> str:
    tokens = _tokenize_follow_up(question)
    if not tokens:
        return ""
    return " ".join(sorted(dict.fromkeys(tokens)))


def _question_family(question: str) -> str:
    tokens = set(_tokenize_follow_up(question))
    if not tokens:
        return "generic"
    if tokens & _KNOWLEDGE_FOLLOW_UP_HINTS:
        return "knowledge"
    if tokens & _PRODUCT_FOLLOW_UP_HINTS:
        return "product"
    return "generic"


def _follow_up_score(
    *,
    question: str,
    user_text: str,
    route: str,
    has_products: bool,
    use_products: bool,
    use_knowledge: bool,
    is_policy_like: bool,
) -> int:
    route_norm = str(route or "").strip().lower()
    family = _question_family(question)
    question_tokens = set(_tokenize_follow_up(question))
    user_tokens = set(_tokenize_follow_up(user_text))
    overlap = len(question_tokens & user_tokens)
    score = overlap

    if route_norm in {"fallback", "fallback_general"}:
        return 0

    if family == "product":
        if has_products and use_products and route_norm in {"catalog", "recommendation"}:
            score += 5
        elif has_products and use_products:
            score += 3
        else:
            score -= 3
    elif family == "knowledge":
        if use_knowledge or is_policy_like or route_norm == "knowledge":
            score += 5
        elif route_norm in {"catalog", "recommendation"} and has_products and use_products:
            score += 1
        else:
            score -= 2
    else:
        if route_norm in {"catalog", "recommendation"} and has_products and use_products:
            score += 2
        elif route_norm == "knowledge" and use_knowledge:
            score += 2

    if "show more" in normalize_text(question):
        score += 1
    if "shipping" in user_tokens or "refund" in user_tokens or "contact" in user_tokens:
        if family == "knowledge":
            score += 1
    if any(token in question_tokens for token in {"gauge", "color", "threading", "material", "price", "stock"}):
        score += 1
    return score


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
    score = _follow_up_score(
        question=question,
        user_text=user_text,
        route=route,
        has_products=has_products,
        use_products=use_products,
        use_knowledge=use_knowledge,
        is_policy_like=is_policy_like,
    )
    return score > 0


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

    route_norm = str(route or "").strip().lower()
    if route_norm in {"fallback", "fallback_general"}:
        return []

    candidates: Dict[str, Tuple[int, int, str]] = {}
    fallback_order: List[Tuple[int, str]] = []
    seen_text: set[str] = set()
    for index, raw in enumerate(list(questions or [])):
        text = str(raw or "").strip()
        if not text:
            continue
        text_key = text.lower()
        if text_key in seen_text:
            continue
        seen_text.add(text_key)

        score = _follow_up_score(
            question=text,
            user_text=user_text,
            route=route,
            has_products=has_products,
            use_products=use_products,
            use_knowledge=use_knowledge,
            is_policy_like=is_policy_like,
        )
        signature = _follow_up_signature(text) or text_key
        fallback_order.append((index, text))
        if score <= 0:
            continue
        current = candidates.get(signature)
        if current is None or score > current[0] or (score == current[0] and index < current[1]):
            candidates[signature] = (score, index, text)

    if not candidates:
        if route_norm in {"catalog", "recommendation", "knowledge"}:
            return [text for _index, text in fallback_order[: max(1, int(limit))]]
        return []

    ranked = sorted(candidates.values(), key=lambda item: (-item[0], item[1]))
    return [text for _score, _index, text in ranked[: max(1, int(limit))]]


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
            _add(f"Try {material} {jewelry_type}")
        if jewelry_type and gauge:
            _add(f"Focus on {gauge} {jewelry_type}")
        if jewelry_type and color:
            _add(f"See {color} {jewelry_type}")
        if jewelry_type and threading:
            _add(f"Try {threading} threading {jewelry_type}")
        if material and not jewelry_type:
            _add(f"Try {material} pieces")
        if gauge and not jewelry_type:
            _add(f"Focus on {gauge} options")

        alt_materials = extract_product_attribute_values(products=products, key="material", limit=3)
        alt_gauges = extract_product_attribute_values(products=products, key="gauge", limit=3)
        for alt in alt_materials:
            if material and alt.lower() == material.lower():
                continue
            if jewelry_type:
                _add(f"See {alt} {jewelry_type}")
            else:
                _add(f"Try {alt} pieces")
        for alt in alt_gauges:
            if gauge and alt.lower() == gauge.lower():
                continue
            if jewelry_type:
                _add(f"Focus on {alt} {jewelry_type}")
            else:
                _add(f"Focus on {alt} options")
    else:
        jewelry_types = extract_product_attribute_values(products=products, key="jewelry_type", limit=2)
        materials = extract_product_attribute_values(products=products, key="material", limit=2)
        gauges = extract_product_attribute_values(products=products, key="gauge", limit=2)
        colors = extract_product_attribute_values(products=products, key="color", limit=2)

        if jewelry_types and materials:
            _add(f"Try {materials[0]} {jewelry_types[0]}")
        for jt in jewelry_types:
            _add(f"See {jt} pieces")
        for material in materials:
            _add(f"Try {material} pieces")
        for gauge in gauges:
            _add(f"Focus on {gauge}")
        for color in colors:
            _add(f"See {color} color pieces")

    if not questions:
        _add("Show popular products")

    return questions[:cap]
