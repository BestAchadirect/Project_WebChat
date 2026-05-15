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


def knowledge_clarify_context(
    *,
    user_text: str,
    location_terms: Sequence[str],
    contact_terms: Sequence[str],
    shipping_terms: Sequence[str],
    refund_terms: Sequence[str],
    payment_terms: Sequence[str],
    warranty_terms: Sequence[str],
    limit: int = 3,
) -> Dict[str, Any]:
    focus = knowledge_clarify_focus(
        user_text=user_text,
        location_terms=location_terms,
        contact_terms=contact_terms,
        shipping_terms=shipping_terms,
        refund_terms=refund_terms,
        payment_terms=payment_terms,
        warranty_terms=warranty_terms,
    )
    return {
        "focus": focus,
        "question": knowledge_clarify_question(
            user_text=user_text,
            location_terms=location_terms,
            contact_terms=contact_terms,
            shipping_terms=shipping_terms,
            refund_terms=refund_terms,
            payment_terms=payment_terms,
            warranty_terms=warranty_terms,
        ),
        "follow_ups": build_knowledge_clarify_follow_ups(
            user_text=user_text,
            location_terms=location_terms,
            contact_terms=contact_terms,
            shipping_terms=shipping_terms,
            refund_terms=refund_terms,
            payment_terms=payment_terms,
            warranty_terms=warranty_terms,
            limit=limit,
        ),
    }


def clarify_mode_for_reason(reason: str) -> str:
    reason_norm = str(reason or "").strip()
    if reason_norm in {"grounding_no_match", "grounding_needs_clarification"}:
        return "strict_grounding"
    if reason_norm == "semantic_concept_unclear":
        return "strict_ambiguity"
    if reason_norm in {"detail_no_match", "detail_request_needs_specific_product"}:
        return "strict_product"
    if reason_norm == "pending_task_missing_slot":
        return "pending_task"
    if reason_norm in {"knowledge_needs_clarification", "knowledge_unavailable"}:
        return "strict_knowledge"
    if reason_norm == "pagination_exhausted":
        return "pagination_exhausted"
    if reason_norm == "pagination_stale":
        return "pagination_stale"
    if reason_norm == "fallback_off_topic_redirect":
        return "scope_redirect"
    if reason_norm == "fallback_gibberish":
        return "gibberish"
    if reason_norm == "fallback_missing_signal":
        return "missing_signal"
    if reason_norm in {"structured_no_match", "attribute_list_no_results"}:
        return "recoverable_product"
    return "broad_help"


def clarify_category_for_reason(reason: str) -> str:
    reason_norm = str(reason or "").strip()
    if reason_norm in {"grounding_no_match", "grounding_needs_clarification"}:
        return "product_grounding"
    if reason_norm in {"attribute_list_no_results", "structured_no_match"}:
        return "product_recovery"
    if reason_norm in {"detail_no_match", "detail_request_needs_specific_product"}:
        return "product_detail"
    if reason_norm == "pending_task_missing_slot":
        return "pending_task"
    if reason_norm == "semantic_concept_unclear":
        return "semantic_guardrail"
    if reason_norm in {"knowledge_needs_clarification"}:
        return "knowledge_clarify"
    if reason_norm in {"knowledge_unavailable"}:
        return "knowledge_unavailable"
    if reason_norm == "fallback_gibberish":
        return "gibberish_rephrase"
    if reason_norm == "fallback_off_topic_redirect":
        return "off_topic_redirect"
    if reason_norm == "fallback_missing_signal":
        return "missing_signal"
    if reason_norm in {"fallback_vague_store_request", "fallback_uncertain", "routing_fallback"}:
        return "vague_store_request"
    if reason_norm in {"pagination_exhausted", "pagination_stale"}:
        return "pagination"
    return "general_clarify"


def clarify_rewrite_allowed_for_reason(reason: str) -> bool:
    return clarify_category_for_reason(reason) == "general_clarify"


def _human_filter_label(
    *,
    key: str,
    value: str,
    display_attribute_value: Callable[[str], str],
) -> str:
    clean_key = str(key or "").strip().lower().replace("_", " ")
    clean_value = display_attribute_value(str(value or "").strip())
    if not clean_key and not clean_value:
        return ""
    if clean_key and clean_value:
        return f"{clean_key} {clean_value}"
    return clean_value or clean_key


def _requirement_summary(
    *,
    attribute_filters: Dict[str, str],
    display_attribute_value: Callable[[str], str],
) -> str:
    labels = [
        _human_filter_label(
            key=key,
            value=value,
            display_attribute_value=display_attribute_value,
        )
        for key, value in dict(attribute_filters or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    ]
    labels = [item for item in labels if item]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


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
    clarify_question: str = "",
) -> Dict[str, Any]:
    reason_norm = str(reason or "missing_details").strip() or "missing_details"
    clarify_mode = clarify_mode_for_reason(reason_norm)
    clarify_category = clarify_category_for_reason(reason_norm)
    clarify_rewrite_allowed = clarify_rewrite_allowed_for_reason(reason_norm)
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
        "clarify_category": clarify_category,
        "clarify_best_effort_help": bool(best_effort_help),
        "clarify_rewrite_allowed": bool(clarify_rewrite_allowed),
    }

    async def _contextual_message(*, fallback: str, payload: Dict[str, Any]) -> str:
        if not clarify_rewrite_allowed:
            return str(fallback or "").strip()
        scoped_payload = dict(payload or {})
        scoped_payload.setdefault(
            "assistant_scope",
            "body jewelry products, stock, pricing, materials, sizes/gauge, store policies, and contact info",
        )
        generated = await generate_contextual_reply(
            kind="clarify",
            reply_language=reply_language,
            payload=scoped_payload,
        )
        return str(generated or fallback).strip()

    if reason_norm in {"grounding_no_match", "grounding_needs_clarification"}:
        requirement_text = _requirement_summary(
            attribute_filters=attribute_filters,
            display_attribute_value=display_attribute_value,
        )
        extra_debug["grounding_clarify_copy"] = True
        if reason_norm == "grounding_no_match":
            if requirement_text:
                message = (
                    f"I couldn't find products that clearly match {requirement_text}. "
                    "Could you share the product type or another detail to narrow it down?"
                )
            else:
                message = (
                    "I couldn't confirm that the products I found match your request closely enough. "
                    "Could you share the product type or one more detail?"
                )
            questions = ["Which product type should I search for?"]
            suggestions = build_product_clarify_follow_ups(
                products=[],
                attribute_filters=attribute_filters,
                needs_knowledge=bool(needs_knowledge),
                limit=3,
            )
        else:
            if requirement_text:
                message = (
                    f"I found possible matches, but I couldn't confirm they match {requirement_text}. "
                    "Which detail matters most for this search?"
                )
            else:
                message = (
                    "I found possible matches, but I couldn't confirm the key detail from your message. "
                    "Which detail matters most for this search?"
                )
            questions = ["Which detail matters most for this search?"]
            suggestions = build_product_clarify_follow_ups(
                products=products,
                attribute_filters=attribute_filters,
                needs_knowledge=bool(needs_knowledge),
                limit=3,
            )
    elif reason_norm in {"attribute_list_no_results", "structured_no_match"}:
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
    elif reason_norm == "knowledge_needs_clarification":
        knowledge_context = knowledge_clarify_context(
            user_text=user_text,
            location_terms=location_terms,
            contact_terms=contact_terms,
            shipping_terms=shipping_terms,
            refund_terms=refund_terms,
            payment_terms=payment_terms,
            warranty_terms=warranty_terms,
        )
        current_focus = str(knowledge_context["focus"] or "general")
        current_question = str(knowledge_context["question"] or "Which policy detail do you need?")
        if str(clarify_question or "").strip():
            current_question = str(clarify_question or "").strip()
        current_follow_ups = list(knowledge_context["follow_ups"] or [])
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
                    "suggested_examples": list(current_follow_ups),
                },
            )
        questions = [current_question]
        suggestions = list(current_follow_ups)
        extra_debug["knowledge_clarify_focus"] = current_focus
    elif reason_norm == "knowledge_unavailable":
        knowledge_context = knowledge_clarify_context(
            user_text=user_text,
            location_terms=location_terms,
            contact_terms=contact_terms,
            shipping_terms=shipping_terms,
            refund_terms=refund_terms,
            payment_terms=payment_terms,
            warranty_terms=warranty_terms,
        )
        current_focus = str(knowledge_context["focus"] or "general")
        current_question = str(knowledge_context["question"] or "Which policy detail do you need?")
        if str(clarify_question or "").strip():
            current_question = str(clarify_question or "").strip()
        current_follow_ups = list(knowledge_context["follow_ups"] or [])
        if current_focus in {"contact", "location"}:
            fallback = "I couldn't retrieve enough contact information right now. Tell me whether you need our sales email, phone number, or showroom address."
        else:
            fallback = f"I couldn't retrieve enough information for a reliable answer right now. {current_question}"
        message = await _contextual_message(
            fallback=fallback,
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": current_focus,
                "knowledge_question": current_question,
                "knowledge_issue_type": "system_weakness",
                "suggested_questions": [current_question],
                "suggested_examples": list(current_follow_ups),
            },
        )
        questions = [current_question]
        suggestions = list(current_follow_ups)
        extra_debug["knowledge_clarify_focus"] = current_focus
    elif reason_norm in {"routing_fallback", "fallback_vague_store_request", "fallback_uncertain"}:
        message = await _contextual_message(
            fallback="I can help with products, store policies, or contact info. What do you want help with right now?",
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": clarify_focus,
                "clarify_category": clarify_category,
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
    elif reason_norm == "pending_task_missing_slot":
        question = str(clarify_question or "").strip() or "Which product are you asking about?"
        message = question
        questions = [question]
        suggestions = [
            "Share the product code",
            "Tell me the material",
            "Tell me the product type",
        ]
    elif reason_norm == "fallback_off_topic_redirect":
        message = await _contextual_message(
            fallback="I can help with products, store policies, and contact info. Tell me which store question you want to handle.",
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": clarify_focus,
                "clarify_category": clarify_category,
                "attribute_filters": attribute_filters,
                "suggested_questions": ["Which store question do you want help with?"],
                "suggested_examples": [
                    "Show titanium jewelry",
                    "How can I contact you?",
                    "What is your return policy?",
                ],
            },
        )
        questions = ["Which store question do you want help with?"]
        suggestions = [
            "Show titanium jewelry",
            "How can I contact you?",
            "What is your return policy?",
        ]
    elif reason_norm == "fallback_missing_signal":
        message = await _contextual_message(
            fallback="I need one more detail to help. Tell me whether you want products, policy details, or contact information.",
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": clarify_focus,
                "clarify_category": clarify_category,
                "attribute_filters": attribute_filters,
                "suggested_questions": ["Which area should I focus on?"],
                "suggested_examples": [
                    "Show titanium jewelry",
                    "What is your shipping policy?",
                    "How can I contact you?",
                ],
            },
        )
        questions = ["Which area should I focus on?"]
        suggestions = [
            "Show titanium jewelry",
            "What is your shipping policy?",
            "How can I contact you?",
        ]
    elif reason_norm == "fallback_gibberish":
        message = await _contextual_message(
            fallback="I didn't catch that message. Can you rephrase it in a few words?",
            payload={
                "reason": reason_norm,
                "user_text": user_text,
                "clarify_focus": clarify_focus,
                "clarify_category": clarify_category,
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
                "clarify_category": clarify_category,
                "attribute_filters": attribute_filters,
                "suggested_questions": list(questions or []),
                "suggested_examples": list(suggestions or []),
            },
        )
    if not questions and reason_norm not in {"pagination_exhausted", "pagination_stale", "semantic_concept_unclear"}:
        questions = ["Which detail should I use to continue?"]
    if not suggestions:
        if reason_norm in {
            "structured_no_match",
            "detail_no_match",
            "detail_request_needs_specific_product",
            "attribute_list_no_results",
            "grounding_no_match",
            "grounding_needs_clarification",
        }:
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
