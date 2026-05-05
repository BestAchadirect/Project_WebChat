from __future__ import annotations

import re
from typing import Iterable, Sequence

KNOWLEDGE_TAG_ORDER = (
    "contact",
    "shipping",
    "refund",
    "returns",
    "payment",
    "warranty",
    "store_overview",
    "custom_orders",
    "ordering",
    "pricing",
    "product_care",
    "samples",
)

KNOWLEDGE_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "contact": (
        "contact",
        "customer service",
        "support",
        "sales team",
        "sale person",
        "sales person",
        "sale representative",
        "salesperson",
        "sales representative",
        "representative",
        "phone",
        "email",
        "whatsapp",
        "line",
        "showroom",
        "address",
        "call us",
    ),
    "shipping": (
        "shipping",
        "ship",
        "delivery",
        "dispatch",
        "tracking",
        "courier",
        "transit",
        "lead time",
        "delivery time",
        "postage",
    ),
    "refund": (
        "refund",
        "money back",
        "reimbursement",
        "credit back",
    ),
    "returns": (
        "return",
        "returns",
        "exchange",
        "returned",
        "send back",
    ),
    "payment": (
        "payment",
        "pay",
        "card",
        "credit card",
        "debit card",
        "bank transfer",
        "invoice",
        "paypal",
        "stripe",
        "cash on delivery",
        "cod",
    ),
    "warranty": (
        "warranty",
        "guarantee",
        "defect",
        "defective",
        "replacement",
        "replace",
        "broken",
    ),
    "store_overview": (
        "about us",
        "company",
        "business",
        "who are you",
        "showroom",
        "location",
        "visit",
        "buy in person",
        "in person",
        "open",
        "close",
        "hours",
    ),
    "custom_orders": (
        "custom",
        "custom order",
        "made to order",
        "bespoke",
        "special order",
        "manufactured",
    ),
    "ordering": (
        "order",
        "ordering",
        "minimum order",
        "moq",
        "bulk order",
        "wholesale order",
    ),
    "pricing": (
        "price",
        "prices",
        "cost",
        "discount",
        "vat",
        "tax",
        "wholesale price",
    ),
    "product_care": (
        "care",
        "clean",
        "cleaning",
        "sterilize",
        "sterilization",
        "sanitize",
    ),
    "samples": (
        "sample",
        "samples",
        "try before",
        "sample request",
    ),
}

PRODUCT_REQUEST_MARKERS = (
    "show me",
    "looking for",
    "looking to buy",
    "find me",
    "do you have",
    "browse",
    "shop",
)
WEAK_PRODUCT_REQUEST_MARKERS = ("i want", "i need")
PRODUCT_DETAIL_MARKERS = (
    "stock for",
    "stock of",
    "availability for",
    "availability of",
    "price of",
    "cost of",
    "photo of",
    "picture of",
    "image of",
    "show image",
    "show me image",
    "what is the price",
    "what's the price",
    "what material",
    "what size",
    "what gauge",
    "what color",
)
PRODUCT_HINT_TERMS = (
    "jewelry",
    "labret",
    "barbell",
    "nose stud",
    "nose ring",
    "ring",
    "stud",
    "titanium",
    "threadless",
    "internally threaded",
    "externally threaded",
    "helix",
    "septum",
)
PRODUCT_ATTRIBUTE_HINT_TERMS = (
    "gold",
    "rose gold",
    "silver",
    "black",
    "white",
    "steel",
    "opal",
    "clear",
)
PRODUCT_CONTEXT_FOLLOW_UP_MARKERS = (
    "what about",
    "how about",
    "what about the",
    "how about the",
    "the other",
    "another",
    " one",
    " ones",
)
PRODUCT_CORRECTION_MARKERS = (
    "no i mean",
    "no, i mean",
    "i mean",
    "actually",
    "not policy",
    "not the policy",
    "not about policy",
)
EXPLICIT_PRODUCT_BROWSE_MARKERS = (
    "see product",
    "see products",
    "show product",
    "show products",
    "buy product",
    "buy products",
    "product with",
    "products with",
    "want to see product",
    "want to see products",
)
POLICY_TAGS = {
    "shipping",
    "refund",
    "returns",
    "payment",
    "warranty",
    "custom_orders",
    "ordering",
    "pricing",
    "product_care",
    "samples",
}
COMPANY_MARKERS = (
    "company",
    "about us",
    "contact",
    "customer service",
    "support",
    "sales person",
    "sales representative",
    "representative",
    "showroom",
    "location",
    "address",
    "visit",
    "hours",
    "open",
    "close",
)
POLICY_MARKERS = (
    "shipping",
    "ship",
    "delivery",
    "refund",
    "return",
    "returns",
    "exchange",
    "payment",
    "pay",
    "credit card",
    "debit card",
    "bank transfer",
    "paypal",
    "warranty",
    "guarantee",
    "custom order",
    "ordering",
    "order",
    "pricing",
    "price",
    "vat",
    "tax",
    "cleaning",
    "sterilize",
    "sterilization",
    "sample",
)
CONTACT_QUERY_MARKERS = (
    "contact",
    "customer service",
    "support",
    "sales",
    "representative",
    "phone",
    "email",
    "whatsapp",
)
LOCATION_QUERY_MARKERS = (
    "where",
    "location",
    "address",
    "showroom",
    "visit",
    "in person",
    "hours",
    "open",
    "close",
)
SMALLTALK_EXACT = {
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "bye",
    "goodbye",
    "ok",
    "okay",
}
SMALLTALK_PREFIXES = ("hi ", "hello ", "hey ", "thanks ", "thank you ")
OFF_TOPIC_VERBS = (
    "write",
    "debug",
    "fix",
    "review",
    "build",
    "generate",
    "create",
    "code",
    "program",
)
OFF_TOPIC_TECH_MARKERS = (
    "python",
    "javascript",
    "typescript",
    "java code",
    "react app",
    "sql query",
    "api endpoint",
    "script",
    "programming",
    "software",
    "bug",
    "stack trace",
)
OFF_TOPIC_SERVICE_MARKERS = (
    "book a flight",
    "flight ticket",
    "hotel booking",
    "weather forecast",
    "news update",
)
PROMPT_INJECTION_MARKERS = (
    "ignore all previous instructions",
    "ignore previous instructions",
    "hidden system prompt",
    "system prompt",
    "reveal your prompt",
    "show me your prompt",
    "full prompt",
)
JAILBREAK_MARKERS = (
    "developer mode",
    "jailbreak",
    "dan mode",
    "ignore the store",
)
UNSAFE_OFF_TOPIC_MARKERS = (
    "phishing",
    "malware",
    "steal credentials",
    "credential theft",
    "scam email",
)


def normalize_signal_text(text: str | None) -> str:
    return " ".join(str(text or "").strip().lower().split())


def contains_any_substring(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles if needle)


def contains_marker(text: str, markers: Sequence[str]) -> bool:
    for marker in list(markers or []):
        clean_marker = str(marker or "").strip().lower()
        if not clean_marker:
            continue
        if " " in clean_marker:
            if clean_marker in text:
                return True
            continue
        if re.search(rf"\b{re.escape(clean_marker)}\b", text):
            return True
    return False


def dedupe_ordered_tags(tags: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for tag in KNOWLEDGE_TAG_ORDER:
        if tag in seen:
            continue
        if tag in tags:
            seen.add(tag)
            ordered.append(tag)
    return ordered


def build_tag_matches(text: str) -> list[str]:
    matched = []
    for tag in KNOWLEDGE_TAG_ORDER:
        if contains_any_substring(text, KNOWLEDGE_TAG_KEYWORDS.get(tag, ())):
            matched.append(tag)
    return dedupe_ordered_tags(matched)


def has_company_signal(text: str, knowledge_tags: Sequence[str]) -> bool:
    tag_set = {str(tag or "").strip().lower() for tag in list(knowledge_tags or []) if str(tag or "").strip()}
    return bool(tag_set.intersection({"contact"})) or contains_marker(text, COMPANY_MARKERS)


def has_policy_signal(text: str, knowledge_tags: Sequence[str]) -> bool:
    tag_set = {str(tag or "").strip().lower() for tag in list(knowledge_tags or []) if str(tag or "").strip()}
    return contains_marker(text, POLICY_MARKERS) or bool(tag_set.intersection(POLICY_TAGS.difference({"payment", "ordering", "pricing"})))


def looks_like_product_search(text: str) -> bool:
    if not text:
        return False
    if any(marker in text for marker in EXPLICIT_PRODUCT_BROWSE_MARKERS):
        return True
    if any(marker in text for marker in PRODUCT_REQUEST_MARKERS):
        return True
    if any(marker in text for marker in WEAK_PRODUCT_REQUEST_MARKERS):
        return any(term in text for term in PRODUCT_HINT_TERMS)
    if any(marker in text for marker in PRODUCT_CONTEXT_FOLLOW_UP_MARKERS):
        return any(term in text for term in PRODUCT_HINT_TERMS + PRODUCT_ATTRIBUTE_HINT_TERMS)
    return any(term in text for term in PRODUCT_HINT_TERMS)


def has_product_correction_override(text: str) -> bool:
    normalized = normalize_signal_text(text)
    if not normalized:
        return False
    has_correction = contains_any_substring(normalized, PRODUCT_CORRECTION_MARKERS)
    has_explicit_product_browse = contains_any_substring(normalized, EXPLICIT_PRODUCT_BROWSE_MARKERS)
    return bool(has_correction and has_explicit_product_browse)


def has_explicit_product_browse_signal(text: str) -> bool:
    normalized = normalize_signal_text(text)
    if not normalized:
        return False
    return bool(
        contains_any_substring(normalized, EXPLICIT_PRODUCT_BROWSE_MARKERS)
        or contains_any_substring(normalized, PRODUCT_REQUEST_MARKERS)
    )


def has_specific_product_hint_signal(text: str) -> bool:
    normalized = normalize_signal_text(text)
    if not normalized:
        return False
    specific_terms = tuple(term for term in PRODUCT_HINT_TERMS if term != "jewelry")
    return bool(
        contains_marker(normalized, specific_terms)
        or contains_marker(normalized, PRODUCT_ATTRIBUTE_HINT_TERMS)
    )


def looks_like_product_detail(text: str, sku_tokens: Sequence[str]) -> bool:
    if list(sku_tokens or []):
        return True
    if any(marker in text for marker in PRODUCT_DETAIL_MARKERS):
        return True
    detail_term = re.search(
        r"\b(stock|availability|price|cost|image|photo|picture|sku|material|size|gauge|color)\b",
        text,
    )
    question_term = re.search(r"\b(what|which|is|are|show|check)\b", text)
    return bool(detail_term and question_term)


def is_smalltalk(text: str) -> bool:
    if not text:
        return False
    if text in SMALLTALK_EXACT:
        return True
    return any(text.startswith(prefix) for prefix in SMALLTALK_PREFIXES)


def is_off_topic_request(text: str) -> bool:
    if not text:
        return False
    if classify_adversarial_request(text):
        return True
    if any(marker in text for marker in OFF_TOPIC_SERVICE_MARKERS):
        return True
    has_tech_marker = any(marker in text for marker in OFF_TOPIC_TECH_MARKERS)
    if has_tech_marker and any(verb in text for verb in OFF_TOPIC_VERBS):
        return True
    return False


def classify_adversarial_request(text: str) -> str:
    normalized = normalize_signal_text(text)
    if not normalized:
        return ""
    if contains_any_substring(normalized, JAILBREAK_MARKERS):
        return "jailbreak_attempt_detected"
    if contains_any_substring(normalized, PROMPT_INJECTION_MARKERS):
        return "prompt_injection_detected"
    if contains_any_substring(normalized, UNSAFE_OFF_TOPIC_MARKERS):
        return "unsafe_request_detected"
    return ""


def _is_gibberish_text(text: str) -> bool:
    if not text:
        return True
    alpha_tokens = re.findall(r"[a-z]+", text.lower())
    if not alpha_tokens or re.search(r"(.)\1{4,}", text.lower()):
        return True
    if len(alpha_tokens) == 1:
        token = alpha_tokens[0]
        vowel_count = sum(1 for ch in token if ch in "aeiou")
        vowel_ratio = float(vowel_count) / max(1, len(token))
        if len(token) >= 8 and (vowel_count <= 1 or vowel_ratio <= 0.30):
            return True
        if any(pattern in token for pattern in ("asdf", "qwer", "zxcv")):
            return True
        if len(token) >= 8 and len(set(token)) <= 3:
            return True
    return False


def classify_fallback_reason(
    *,
    text: str,
    route_reason: str,
    blank_reason: str,
    default_reason: str,
    vague_hints: Sequence[str] = (),
    has_product_signal: bool = False,
    has_knowledge_signal: bool = False,
    has_smalltalk_signal: bool = False,
    has_off_topic_signal: bool = False,
) -> str:
    route_reason_norm = str(route_reason or "").strip()
    if route_reason_norm in {
        "routing_fallback",
        "fallback_vague_store_request",
        "fallback_off_topic_redirect",
        "fallback_gibberish",
        "fallback_missing_signal",
        "knowledge_unavailable",
        "knowledge_needs_clarification",
        "pending_task_missing_slot",
    }:
        return route_reason_norm

    normalized = normalize_signal_text(text)
    if not normalized:
        return blank_reason

    if has_off_topic_signal or has_smalltalk_signal or is_off_topic_request(normalized):
        return "fallback_off_topic_redirect"

    if _is_gibberish_text(normalized):
        return "fallback_gibberish"

    for hint in list(vague_hints or []):
        clean_hint = str(hint or "").strip().lower()
        if clean_hint and clean_hint in normalized:
            return "fallback_vague_store_request"

    if has_product_signal or has_knowledge_signal:
        return blank_reason

    return default_reason


def build_company_query(text: str, knowledge_tags: Sequence[str]) -> tuple[str, bool]:
    clean_text = normalize_signal_text(text)
    tag_set = {str(tag or "").strip().lower() for tag in list(knowledge_tags or []) if str(tag or "").strip()}
    if "contact" in tag_set or any(marker in clean_text for marker in CONTACT_QUERY_MARKERS):
        return "how can I contact customer service", False
    if any(marker in clean_text for marker in LOCATION_QUERY_MARKERS):
        return "where is your company located", True
    return "about your company", True
