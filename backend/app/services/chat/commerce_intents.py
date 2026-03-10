from __future__ import annotations

import re
from typing import Callable, List, Optional

SUPPORTED_INTENTS = {
    "browse_products",
    "search_specific",
    "knowledge_query",
    "off_topic",
    "compare_products",
    "recommend_products",
}

UNSUPPORTED_TRANSACTION_INTENTS = {
    "add_to_cart",
    "view_cart",
    "start_checkout",
}

PRODUCT_INTENTS = {
    "browse_products",
    "search_specific",
    "compare_products",
    "recommend_products",
}


def is_store_overview_request(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    patterns = (
        r"\bwhat do you have(?: in your store)?\b",
        r"\bwhat do you sell\b",
        r"\bwhat do you carry\b",
        r"\bwhat products do you have\b",
        r"\bwhat products do you carry\b",
        r"\bwhat kind of (?:products|jewelry) do you have\b",
        r"\bshow me what you have\b",
        r"\bwhat's in your store\b",
        r"\byour catalog\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def is_compare_request(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return bool(
        re.search(r"\b(compare|vs|versus)\b", normalized)
        or "difference between" in normalized
    )


def is_recommendation_request(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    patterns = (
        r"\brecommend(?:ed|ation|ations)?\b",
        r"\bsuggest(?:ed|ion|ions)?\b",
        r"\bhelp me choose\b",
        r"\bwhich one should i choose\b",
        r"\bwhat do you recommend\b",
        r"\bsimilar items\b",
        r"\bsimilar products\b",
        r"\bwhat goes with\b",
        r"\bgo(?:es)? with\b",
        r"\bpair(?:s)? with\b",
        r"\bmatch(?:es)? with\b",
        r"\bfits (?:this|with)\b",
        r"\battachments? for\b",
        r"\baccessories? for\b",
        r"\btops? for\b",
        r"\bends? for\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def is_product_intent(*, intent: str, show_products: bool = False) -> bool:
    return str(intent or "").strip().lower() in PRODUCT_INTENTS or bool(show_products)


def normalize_intent(
    *,
    raw_intent: str,
    user_text: str,
    show_products: bool,
    has_product_signal: bool,
) -> str:
    intent = str(raw_intent or "").strip().lower()
    if intent in SUPPORTED_INTENTS:
        return intent
    if intent in UNSUPPORTED_TRANSACTION_INTENTS:
        return "knowledge_query"
    if is_compare_request(user_text):
        return "compare_products"
    if is_recommendation_request(user_text):
        return "recommend_products"
    if is_store_overview_request(user_text):
        return "browse_products"
    if show_products or has_product_signal:
        return "browse_products"
    return "knowledge_query"


def extract_compare_sku_tokens(
    *,
    user_text: str,
    nlu_product_code: str,
    sku_token: Optional[str],
    extract_sku_like_tokens: Callable[[str], List[str]],
    clean_code_candidate: Callable[[str], str],
    looks_like_code: Callable[[str], bool],
) -> List[str]:
    candidates: List[str] = []
    for raw in list(extract_sku_like_tokens(user_text or "")) + [sku_token or "", nlu_product_code or ""]:
        clean = clean_code_candidate(str(raw or ""))
        if not clean or not looks_like_code(clean):
            continue
        candidates.append(clean.lower())

    deduped: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped
