from __future__ import annotations

from typing import Any, Dict, List, Sequence

from app.services.chat.presentation import reply_tone


RESPONSE_COPY_REGISTRY: Dict[str, Sequence[str]] = {
    "product_match.generic": (
        "I found products that match what you're looking for.",
        "I found a few matching products for you.",
        "Here are the closest matching products.",
    ),
    "product_match.attribute": (
        "I found products that match your request {phrase}.",
        "Good choice. I found matching options {phrase}.",
        "Nice, these products match your request {phrase}.",
    ),
    "product_summary.generic": (
        "I found {focus_label} that are {benefit_text}.",
        "Here are {focus_label} that are {benefit_text}.",
        "I pulled up {focus_label} that are {benefit_text}.",
    ),
    "product_summary.attribute": (
        "I found {focus_label} {phrase} that are {benefit_text}.",
        "Here are {focus_label} {phrase} that are {benefit_text}.",
        "I pulled up {focus_label} {phrase} that are {benefit_text}.",
    ),
    "recommendation_summary.generic": (
        "I found {focus_label} that are {benefit_text}.",
        "Here are {focus_label} that are {benefit_text}.",
        "I pulled up {focus_label} that are {benefit_text}.",
    ),
    "recommendation_summary.complementary": (
        "I found {focus_label} for your {anchor_type} that are {benefit_text}.",
        "Here are {focus_label} for your {anchor_type} that are {benefit_text}.",
        "I pulled up {focus_label} for your {anchor_type} that are {benefit_text}.",
    ),
    "recommendation_summary.empty": (
        "I found a few matching options.",
        "I found a few matching options to start with.",
        "Here are a few matching options to start with.",
    ),
}


def _render_variants(variants: Sequence[str], **values: Any) -> List[str]:
    rendered: List[str] = []
    for raw in list(variants or []):
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            rendered.append(text.format(**values))
        except Exception:
            rendered.append(text)
    return rendered


def pick_response_copy(
    *,
    key: str,
    user_text: str,
    values: Dict[str, Any] | None = None,
    fallback_variants: Sequence[str] | None = None,
) -> str:
    variants = list(fallback_variants or RESPONSE_COPY_REGISTRY.get(str(key or "").strip(), []))
    if not variants:
        return ""
    rendered = _render_variants(variants, **dict(values or {}))
    return reply_tone.pick_variant(
        user_text=user_text,
        key=str(key or "").strip(),
        variants=rendered,
    )
