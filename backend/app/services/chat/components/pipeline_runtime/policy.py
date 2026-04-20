from __future__ import annotations

DETAIL_CLARIFY_FIELDS = {"price", "stock"}

HIGH_RISK_KNOWLEDGE_TERMS = {
    "shipping",
    "delivery",
    "refund",
    "return",
    "payment",
    "warranty",
    "customs",
    "contact",
    "sales contact",
    "sales team",
    "support",
    "customer service",
    "email",
    "phone",
    "hotline",
    "whatsapp",
}

CONTACT_KNOWLEDGE_TERMS = {
    "contact",
    "sales contact",
    "sales team",
    "support",
    "customer service",
    "email",
    "phone",
    "hotline",
    "whatsapp",
}

LOCATION_KNOWLEDGE_TERMS = {
    "where",
    "location",
    "address",
    "showroom",
    "in person",
    "visit",
    "pickup",
    "pick up",
}

SHIPPING_KNOWLEDGE_TERMS = {"shipping", "delivery", "lead time", "arrive", "ship"}
REFUND_KNOWLEDGE_TERMS = {"refund", "return", "exchange"}
PAYMENT_KNOWLEDGE_TERMS = {"payment", "pay", "invoice", "wire", "bank transfer", "credit card"}
WARRANTY_KNOWLEDGE_TERMS = {"warranty", "guarantee"}

KNOWLEDGE_UNAVAILABLE_MESSAGE = "I can share a short answer now, but detailed knowledge search is unavailable."

DESIGN_DISCOVERY_TERMS = ("design", "style", "look", "aesthetic")
FALLBACK_VALID_HINTS = (
    "labret",
    "barbell",
    "ring",
    "body part",
    "presentation",
    "feature",
    "opal",
    "titanium",
    "steel",
    "gold",
    "shipping",
    "refund",
    "contact",
    "policy",
    "price",
    "stock",
    "recommend",
)

OFF_TOPIC_REDIRECT_OPTIONS = (
    "If you want, tell me what jewelry type or material you're looking for.",
    "If you want, tell me what body part or presentation type you're looking for.",
    "If you want, ask me about products, stock, or store policies.",
    "If you want, share your preferred style and I can suggest products.",
)
