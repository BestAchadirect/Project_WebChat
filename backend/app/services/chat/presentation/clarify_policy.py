from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence

from app.prompts.ambiguity import get_ambiguity_policy
from app.services.chat.components.builders.contextual_messages import generate_contextual_reply
from app.services.chat.text_normalization import normalize_user_text


def dedupe_follow_up_questions(items: Sequence[str], *, limit: int = 5) -> List[str]:
    deduped: List[str] = []
    seen: set[str] = set()
    for raw in list(items or []):
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
        if len(deduped) >= max(1, int(limit)):
            break
    return deduped


def product_sku(product: Any) -> str:
    return str(getattr(product, "sku", "") or "").strip()


def product_master_code(product: Any) -> str:
    attrs = dict(getattr(product, "attributes", {}) or {})
    for value in (
        attrs.get("master_code"),
        getattr(product, "title", None),
        getattr(product, "name", None),
        getattr(product, "sku", None),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def build_product_clarify_follow_ups(
    *,
    products: Sequence[Any],
    attribute_filters: Dict[str, str],
    needs_knowledge: bool,
    limit: int = 3,
) -> List[str]:
    follow_ups: List[str] = []
    for product in list(products or [])[:3]:
        master_code = product_master_code(product)
        if master_code:
            follow_ups.append(f"Show details for {master_code}")
    if not follow_ups:
        if "material" not in attribute_filters:
            follow_ups.extend(["Show titanium jewelry", "Show gold jewelry"])
        if "jewelry_type" not in attribute_filters:
            follow_ups.append("Show labret")
    if needs_knowledge:
        follow_ups.append("How can I contact you?")
    return dedupe_follow_up_questions(follow_ups, limit=limit)


def knowledge_clarify_focus(
    *,
    user_text: str,
    location_terms: Sequence[str],
    contact_terms: Sequence[str],
    shipping_terms: Sequence[str],
    refund_terms: Sequence[str],
    payment_terms: Sequence[str],
    warranty_terms: Sequence[str],
) -> str:
    normalized = normalize_user_text(user_text)
    if not normalized:
        return "general"
    if any(term in normalized for term in location_terms):
        return "location"
    if any(term in normalized for term in contact_terms):
        return "contact"
    if any(term in normalized for term in shipping_terms):
        return "shipping"
    if any(term in normalized for term in refund_terms):
        return "refund"
    if any(term in normalized for term in payment_terms):
        return "payment"
    if any(term in normalized for term in warranty_terms):
        return "warranty"
    return "general"


def knowledge_clarify_question(
    *,
    user_text: str,
    location_terms: Sequence[str],
    contact_terms: Sequence[str],
    shipping_terms: Sequence[str],
    refund_terms: Sequence[str],
    payment_terms: Sequence[str],
    warranty_terms: Sequence[str],
) -> str:
    focus = knowledge_clarify_focus(
        user_text=user_text,
        location_terms=location_terms,
        contact_terms=contact_terms,
        shipping_terms=shipping_terms,
        refund_terms=refund_terms,
        payment_terms=payment_terms,
        warranty_terms=warranty_terms,
    )
    if focus in {"contact", "location"}:
        return "Do you need our sales email, phone number, or showroom address?"
    if focus == "shipping":
        return "Do you need shipping cost, delivery time, or destination coverage?"
    if focus == "refund":
        return "Do you need return eligibility, refund timing, or exchange terms?"
    if focus == "payment":
        return "Do you need accepted payment methods, invoice details, or transfer instructions?"
    if focus == "warranty":
        return "Do you need warranty coverage, duration, or claim steps?"
    return "Which policy detail do you need?"


def build_knowledge_clarify_follow_ups(
    *,
    user_text: str,
    location_terms: Sequence[str],
    contact_terms: Sequence[str],
    shipping_terms: Sequence[str],
    refund_terms: Sequence[str],
    payment_terms: Sequence[str],
    warranty_terms: Sequence[str],
    limit: int = 3,
) -> List[str]:
    focus = knowledge_clarify_focus(
        user_text=user_text,
        location_terms=location_terms,
        contact_terms=contact_terms,
        shipping_terms=shipping_terms,
        refund_terms=refund_terms,
        payment_terms=payment_terms,
        warranty_terms=warranty_terms,
    )
    if focus in {"contact", "location"}:
        return dedupe_follow_up_questions(
            [
                "What is your sales email?",
                "What is your phone number?",
                "What is your showroom address?",
            ],
            limit=limit,
        )
    if focus == "shipping":
        return dedupe_follow_up_questions(
            [
                "What is your shipping policy?",
                "How long is delivery?",
                "Do you ship internationally?",
            ],
            limit=limit,
        )
    if focus == "refund":
        return dedupe_follow_up_questions(
            [
                "What is your refund policy?",
                "What can I return?",
                "How long do refunds take?",
            ],
            limit=limit,
        )
    if focus == "payment":
        return dedupe_follow_up_questions(
            [
                "What payment methods do you accept?",
                "Can I pay by bank transfer?",
                "Do you issue invoices?",
            ],
            limit=limit,
        )
    if focus == "warranty":
        return dedupe_follow_up_questions(
            [
                "What is your warranty policy?",
                "What does the warranty cover?",
                "How do I claim warranty support?",
            ],
            limit=limit,
        )
    normalized = normalize_user_text(user_text)
    follow_ups: List[str] = []
    if "shipping" in normalized or "delivery" in normalized:
        follow_ups.extend(["What is your shipping policy?", "How long is delivery?"])
    if "refund" in normalized or "return" in normalized:
        follow_ups.extend(["What is your refund policy?", "What can I return?"])
    if any(term in normalized for term in {"contact", "support", "sales", "email", "phone", "whatsapp"}):
        follow_ups.extend(["How can I contact you?", "How can I contact your sales team?"])
    if not follow_ups:
        follow_ups.extend(
            [
                "What is your shipping policy?",
                "What is your refund policy?",
                "How can I contact you?",
            ]
        )
    return dedupe_follow_up_questions(follow_ups, limit=limit)


def clarify_mode_for_reason(reason: str) -> str:
    reason_norm = str(reason or "").strip()
    if reason_norm == "semantic_concept_unclear":
        return "strict_ambiguity"
    if reason_norm in {"detail_no_match", "detail_request_needs_specific_product"}:
        return "strict_product"
    if reason_norm in {"knowledge_needs_clarification", "knowledge_unavailable"}:
        return "strict_knowledge"
    if reason_norm == "pagination_exhausted":
        return "pagination_exhausted"
    if reason_norm == "pagination_stale":
        return "pagination_stale"
    if reason_norm == "fallback_gibberish":
        return "gibberish"
    if reason_norm in {"structured_no_match", "attribute_list_no_results"}:
        return "recoverable_product"
    return "broad_help"


async def build_clarify_policy(
    *,
    reason: str,
    user_text: str,
    reply_language: str,
    products: Sequence[Any],
    attribute_filters: Dict[str, str],
    needs_knowledge: bool,
    requested_fields: Sequence[str],
    clarify_focus: str,
    display_attribute_value: Callable[[str], str],
    build_pagination_exhausted_follow_ups: Callable[..., List[str]],
    location_terms: Sequence[str],
    contact_terms: Sequence[str],
    shipping_terms: Sequence[str],
    refund_terms: Sequence[str],
    payment_terms: Sequence[str],
    warranty_terms: Sequence[str],
) -> Dict[str, Any]:
    reason_norm = str(reason or "missing_details").strip() or "missing_details"
    clarify_mode = clarify_mode_for_reason(reason_norm)
    best_effort_help = clarify_mode in {
        "recoverable_product",
        "broad_help",
        "strict_knowledge",
        "pagination_exhausted",
    }
    message = ""
    questions: List[str] = []
    suggestions: List[str] = []
    extra_debug: Dict[str, Any] = {
        "clarify_mode": clarify_mode,
        "clarify_best_effort_help": bool(best_effort_help),
    }

    async def _contextual_message(*, fallback: str, payload: Dict[str, Any]) -> str:
        generated = await generate_contextual_reply(
            kind="clarify",
            reply_language=reply_language,
            payload=payload,
        )
        return str(generated or fallback).strip()

    if reason_norm in {"attribute_list_no_results", "structured_no_match"}:
        if reason_norm == "attribute_list_no_results":
            message = await _contextual_message(
                fallback="What material, style, or gauge should I use to narrow this down?",
                payload={
                    "reason": reason_norm,
                    "user_text": user_text,
                    "clarify_focus": clarify_focus,
                    "attribute_filters": attribute_filters,
                    "requested_fields": list(requested_fields or []),
                    "suggested_questions": ["Which filter should I broaden?"],
                    "suggested_examples": [
                        "Share material",
                        "Share style",
                        "Share gauge",
                    ],
                },
            )
            questions = ["Which filter should I broaden?"]
        else:
            message = await _contextual_message(
                fallback="What material, style, or gauge should I use to narrow this down?",
                payload={
                    "reason": reason_norm,
                    "user_text": user_text,
                    "clarify_focus": clarify_focus,
                    "attribute_filters": attribute_filters,
                    "requested_fields": list(requested_fields or []),
                    "suggested_questions": ["Which detail should I use to continue?"],
                    "suggested_examples": [
                        "Share material",
                        "Share style",
                        "Share gauge",
                    ],
                },
            )
            questions = ["Which detail should I use to continue?"]
        suggestions = build_product_clarify_follow_ups(
            products=products,
            attribute_filters=attribute_filters,
            needs_knowledge=bool(needs_knowledge),
            limit=3,
        )
    elif reason_norm == "semantic_concept_unclear":
        focus = str(clarify_focus or "").strip().lower()
        policy = get_ambiguity_policy(focus)
        if policy:
            extra_debug["ambiguity_focus_family"] = str(policy.get("focus_family") or focus or "")
            message = await _contextual_message(
                fallback=str(policy.get("message_hint") or "What detail should I use to narrow this down?"),
                payload={
                    "reason": reason_norm,
                    "user_text": user_text,
                    "clarify_focus": focus,
                    "policy_family": str(policy.get("focus_family") or focus or ""),
                    "clarify_question": str(policy.get("message_hint") or ""),
                    "clarify_instruction": "Write a direct customer-facing question. Use the supplied clarify_question if it is present, and keep it natural.",
                    "attribute_filters": attribute_filters,
                },
            )
            questions = []
            suggestions = []
        else:
            extra_debug["ambiguity_focus_family"] = focus
            message = await _contextual_message(
                fallback="What detail should I use to narrow this down?",
                payload={
                    "reason": reason_norm,
                    "user_text": user_text,
                    "clarify_focus": focus,
                    "clarify_question": "What detail should I use to narrow this down?",
                    "clarify_instruction": "Write a direct customer-facing question. Use the supplied clarify_question if it is present, and keep it natural.",
                    "attribute_filters": attribute_filters,
                },
            )
            questions = []
            suggestions = []
    elif reason_norm in {"detail_no_match", "detail_request_needs_specific_product"}:
        requested = {str(item or "").strip().lower() for item in list(requested_fields or []) if str(item or "").strip()}
        jewelry_type = str((attribute_filters or {}).get("jewelry_type") or "").strip().lower()
        subject = jewelry_type or "product"
        action = "look that up"
        if "price" in requested and "stock" in requested:
            action = "check the price and stock"
        elif "price" in requested:
            action = "check the price"
        elif "stock" in requested:
            action = "check the stock"
        if reason_norm == "detail_no_match":
            message = await _contextual_message(
                fallback=f"I couldn't find a product that matches those details. Share a SKU or more specific details and I can {action}.",
                payload={
                    "reason": reason_norm,
                    "user_text": user_text,
                    "clarify_focus": clarify_focus,
                    "attribute_filters": attribute_filters,
                    "requested_fields": list(requested_fields or []),
                    "suggested_questions": ["Which exact product should I use?"],
                    "suggested_examples": [
                        "Share a SKU",
                        "Add material",
                        "Add size",
                    ],
                },
            )
        else:
            message = await _contextual_message(
                fallback=f"I'm not sure which {subject} you mean. Share a SKU or add more details and I can {action}.",
                payload={
                    "reason": reason_norm,
                    "user_text": user_text,
                    "clarify_focus": clarify_focus,
                    "attribute_filters": attribute_filters,
                    "requested_fields": list(requested_fields or []),
                    "suggested_questions": ["Which exact product should I use?"],
                    "suggested_examples": [
                        "Share a SKU",
                        "Add material",
                        "Add size",
                    ],
                },
            )
        questions = ["Which exact product should I use?"]
    elif reason_norm == "pagination_exhausted":
        material = display_attribute_value(str((attribute_filters or {}).get("material") or ""))
        jewelry_type = display_attribute_value(str((attribute_filters or {}).get("jewelry_type") or ""))
        scope_bits = [part for part in [material, jewelry_type] if part]
        scope_label = " ".join(scope_bits).strip()
        if scope_label:
            scope_label = f"{scope_label} matches"
        else:
            scope_label = "matching products"
        message = await _contextual_message(
            fallback=(
                f"I reached the end of the current {scope_label} I found, but I can broaden the search if you'd like."
            ),
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": clarify_focus,
                "attribute_filters": attribute_filters,
                "suggested_questions": [],
                "suggested_examples": [
                    "Show titanium jewelry",
                    "Show gold jewelry",
                    "Show labret",
                ],
            },
        )
        questions = []
        suggestions = build_pagination_exhausted_follow_ups(
            attribute_filters=attribute_filters,
            limit=3,
        )
    elif reason_norm == "pagination_stale":
        message = await _contextual_message(
            fallback="That pagination button is already outdated. Please use the latest Show more button.",
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": clarify_focus,
                "attribute_filters": attribute_filters,
                "requested_fields": list(requested_fields or []),
                "suggested_questions": [],
                "suggested_examples": [
                    "Use the latest Show more button",
                    "Ask for a fresh search",
                ],
            },
        )
        questions = []
        suggestions = []
    elif reason_norm in {"knowledge_needs_clarification", "knowledge_unavailable"}:
        current_focus = knowledge_clarify_focus(
            user_text=user_text,
            location_terms=location_terms,
            contact_terms=contact_terms,
            shipping_terms=shipping_terms,
            refund_terms=refund_terms,
            payment_terms=payment_terms,
            warranty_terms=warranty_terms,
        )
        current_question = knowledge_clarify_question(
            user_text=user_text,
            location_terms=location_terms,
            contact_terms=contact_terms,
            shipping_terms=shipping_terms,
            refund_terms=refund_terms,
            payment_terms=payment_terms,
            warranty_terms=warranty_terms,
        )
        if current_focus in {"contact", "location"}:
            message = await _contextual_message(
                fallback="I can help with contact details. Do you need our sales email, phone number, or showroom address?",
                payload={
                    "reason": reason_norm,
                    "user_text": user_text,
                    "clarify_focus": current_focus,
                    "knowledge_question": current_question,
                    "suggested_questions": [current_question],
                    "suggested_examples": [
                        "Sales email",
                        "Phone number",
                        "Showroom address",
                    ],
                },
            )
        else:
            message = await _contextual_message(
                fallback=f"I can help with that. {current_question}",
                payload={
                    "reason": reason_norm,
                    "user_text": user_text,
                    "clarify_focus": current_focus,
                    "knowledge_question": current_question,
                    "suggested_questions": [current_question],
                    "suggested_examples": list(build_knowledge_clarify_follow_ups(
                        user_text=user_text,
                        location_terms=location_terms,
                        contact_terms=contact_terms,
                        shipping_terms=shipping_terms,
                        refund_terms=refund_terms,
                        payment_terms=payment_terms,
                        warranty_terms=warranty_terms,
                        limit=3,
                    )),
                },
            )
        questions = [current_question]
        suggestions = build_knowledge_clarify_follow_ups(
            user_text=user_text,
            location_terms=location_terms,
            contact_terms=contact_terms,
            shipping_terms=shipping_terms,
            refund_terms=refund_terms,
            payment_terms=payment_terms,
            warranty_terms=warranty_terms,
            limit=3,
        )
        extra_debug["knowledge_clarify_focus"] = current_focus
    elif reason_norm in {"routing_fallback", "fallback_uncertain"}:
        message = await _contextual_message(
            fallback="I can help right away. Tell me whether you need products, policy details, or contact info.",
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": clarify_focus,
                "attribute_filters": attribute_filters,
                "suggested_questions": ["What do you want help with right now?"],
                "suggested_examples": [
                    "Show titanium jewelry",
                    "How can I contact you?",
                    "What is your shipping policy?",
                ],
            },
        )
        questions = ["What do you want help with right now?"]
        suggestions = [
            "Show titanium jewelry",
            "How can I contact you?",
            "What is your shipping policy?",
        ]
    elif reason_norm == "fallback_gibberish":
        message = await _contextual_message(
            fallback="I didn't catch that message. Can you rephrase it in a few words?",
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": clarify_focus,
                "attribute_filters": attribute_filters,
                "suggested_questions": ["Can you rephrase your request?"],
                "suggested_examples": [
                    "Show titanium jewelry",
                    "How can I contact you?",
                    "Do you have in-stock products?",
                ],
            },
        )
        questions = ["Can you rephrase your request?"]
        suggestions = [
            "Show titanium jewelry",
            "How can I contact you?",
            "Do you have in-stock products?",
        ]

    if not message:
        message = await _contextual_message(
            fallback="What detail should I use to narrow this down?",
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": clarify_focus,
                "attribute_filters": attribute_filters,
                "suggested_questions": list(questions or []),
                "suggested_examples": list(suggestions or []),
            },
        )
    if not questions and reason_norm not in {"pagination_exhausted", "pagination_stale", "semantic_concept_unclear"}:
        questions = ["Which detail should I use to continue?"]
    if not suggestions:
        if reason_norm in {"structured_no_match", "detail_no_match", "detail_request_needs_specific_product", "attribute_list_no_results"}:
            suggestions = build_product_clarify_follow_ups(
                products=products,
                attribute_filters=attribute_filters,
                needs_knowledge=bool(needs_knowledge),
                limit=3,
            )
        elif reason_norm in {"pagination_stale", "semantic_concept_unclear"}:
            suggestions = []
        else:
            suggestions = build_knowledge_clarify_follow_ups(
                user_text=user_text,
                location_terms=location_terms,
                contact_terms=contact_terms,
                shipping_terms=shipping_terms,
                refund_terms=refund_terms,
                payment_terms=payment_terms,
                warranty_terms=warranty_terms,
                limit=3,
            )

    return {
        "reason": reason_norm,
        "message": str(message or "").strip(),
        "questions": list(questions or []),
        "suggestions": list(suggestions or []),
        "extra_debug": dict(extra_debug or {}),
    }
