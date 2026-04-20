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
    return bool(tag_set.intersection({"contact", "store_overview"})) or contains_marker(text, COMPANY_MARKERS)


def has_policy_signal(text: str, knowledge_tags: Sequence[str]) -> bool:
    tag_set = {str(tag or "").strip().lower() for tag in list(knowledge_tags or []) if str(tag or "").strip()}
    return contains_marker(text, POLICY_MARKERS) or bool(tag_set.intersection(POLICY_TAGS.difference({"payment", "ordering", "pricing"})))


def looks_like_product_search(text: str) -> bool:
    if not text:
        return False
    if any(marker in text for marker in PRODUCT_REQUEST_MARKERS):
        return True
    if any(marker in text for marker in WEAK_PRODUCT_REQUEST_MARKERS):
        return any(term in text for term in PRODUCT_HINT_TERMS)
    return any(term in text for term in PRODUCT_HINT_TERMS)


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


def build_company_query(text: str, knowledge_tags: Sequence[str]) -> tuple[str, bool]:
    clean_text = normalize_signal_text(text)
    tag_set = {str(tag or "").strip().lower() for tag in list(knowledge_tags or []) if str(tag or "").strip()}
    if "contact" in tag_set or any(marker in clean_text for marker in CONTACT_QUERY_MARKERS):
        return "how can I contact customer service", False
    if any(marker in clean_text for marker in LOCATION_QUERY_MARKERS):
        return "where is your company located", True
    return "about your company", True
