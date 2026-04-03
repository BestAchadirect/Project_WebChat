from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence

from app.prompts.ambiguity import get_ambiguity_policy
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
    if reason_norm == "fallback_gibberish":
        return "gibberish"
    if reason_norm in {"structured_no_match", "attribute_list_no_results"}:
        return "recoverable_product"
    return "broad_help"


def build_clarify_policy(
    *,
    reason: str,
    user_text: str,
    tone_pick: Callable[[str, Sequence[str]], str],
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

    if reason_norm in {"attribute_list_no_results", "structured_no_match"}:
        if reason_norm == "attribute_list_no_results":
            message = tone_pick(
                "clarify:attribute_list_no_results",
                [
                    "I couldn't find that exact filter, but I can still help narrow it down with one detail like material, style, or gauge.",
                    "That filter is too narrow right now. Share one broader detail and I'll find close options.",
                    "No matching attribute options yet. Try one broader detail and I'll refine it for you.",
                ],
            )
            questions = ["Which filter should I broaden?"]
        else:
            message = tone_pick(
                "clarify:structured_no_match:humanized",
                [
                    "I can still help find something close. Share one detail like material, style, or gauge and I'll narrow the search.",
                    "No exact match yet, but I can find alternatives. Tell me one preference and I'll refine it.",
                    "I can help from here. Give me one detail like material, style, or gauge and I'll show the closest options.",
                ],
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
            message = tone_pick(
                str(policy.get("message_key") or f"clarify:{reason_norm}:{focus or 'default'}"),
                list(policy.get("message_variants") or []),
            )
            questions = list(policy.get("questions") or [])
            suggestions = list(policy.get("suggestions") or [])
        else:
            message = tone_pick(
                "clarify:semantic_concept_unclear",
                [
                    "I need one detail to interpret that product concept correctly. Can you be a bit more specific?",
                    "That concept can mean a few different things. Tell me which type you want and I'll narrow it down.",
                    "I can help, but I need one more detail about what you mean before I show products.",
                ],
            )
            questions = ["Which product concept should I focus on?"]
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
        message = tone_pick(
            f"clarify:{reason_norm}",
            [
                f"I'm not sure which {subject} you mean. Share a SKU or add details like material, gauge, size, or color, and I can {action}.",
                f"I need one exact product to {action}. Share a SKU or fewer filters so I can continue.",
                f"Please share a SKU or more specific product details so I can {action}.",
            ],
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
        message = tone_pick(
            "clarify:pagination_exhausted",
            [
                f"I reached the end of the {scope_label} I found.",
                f"I've shown the last page of {scope_label} I found.",
                f"If you want, I can still help narrow by material, style, or gauge.",
            ],
        )
        questions = []
        suggestions = build_pagination_exhausted_follow_ups(
            attribute_filters=attribute_filters,
            limit=3,
        )
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
            key = "clarify:knowledge_contact_context" if reason_norm == "knowledge_needs_clarification" else "clarify:knowledge_contact_unavailable"
            message = tone_pick(
                key,
                [
                    "I can help with contact details. Do you need our sales email, phone number, or showroom address?",
                    "I can share that. Do you want email, phone, or showroom address?",
                    "Tell me whether you need email, phone, or showroom address and I will help.",
                ],
            )
        else:
            key = "clarify:knowledge_context" if reason_norm == "knowledge_needs_clarification" else "clarify:knowledge_unavailable"
            message = tone_pick(
                key,
                [
                    f"I can help with that. {current_question}",
                    f"To answer accurately, I need one detail. {current_question}",
                    f"Let's narrow this quickly. {current_question}",
                ],
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
        message = tone_pick(
            "clarify:fallback_uncertain",
            [
                "I can help right away. Tell me whether you need products, policy details, or contact info.",
                "I can assist with products, policy, or contact details. Which one should I focus on?",
                "Tell me your main goal and I'll route this correctly: products, policy, or contact.",
            ],
        )
        questions = ["What do you want help with right now?"]
        suggestions = [
            "Show titanium jewelry",
            "How can I contact you?",
            "What is your shipping policy?",
        ]
    elif reason_norm == "fallback_gibberish":
        message = tone_pick(
            "clarify:fallback_gibberish",
            [
                "I didn't catch that message. Can you rephrase it in a few words?",
                "That came through unclear. Please rephrase what you need.",
                "I couldn't parse that yet. Can you type it again with what you want help with?",
            ],
        )
        questions = ["Can you rephrase your request?"]
        suggestions = [
            "Show titanium jewelry",
            "How can I contact you?",
            "Do you have in-stock products?",
        ]

    if not message:
        message = tone_pick(
            f"clarify:{reason_norm}:default",
            [
                "Share a little more detail so I can match the right products.",
                "I can help faster if you add one or two more details.",
                "Give me a bit more detail and I will narrow this down.",
            ],
        )
    if not questions and reason_norm != "pagination_exhausted":
        questions = ["Which detail should I use to continue?"]
    if not suggestions:
        if reason_norm in {"structured_no_match", "detail_no_match", "detail_request_needs_specific_product", "attribute_list_no_results"}:
            suggestions = build_product_clarify_follow_ups(
                products=products,
                attribute_filters=attribute_filters,
                needs_knowledge=bool(needs_knowledge),
                limit=3,
            )
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
