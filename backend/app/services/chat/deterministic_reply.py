from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.schemas.chat import ChatResponse, ProductCard


def embedding_failure_reply_text(*, use_products: bool, use_knowledge: bool) -> str:
    if use_products and use_knowledge:
        return "I'm having trouble reaching search right now. Please try again in a moment."
    if use_products:
        return "I'm having trouble searching products right now. Please try again in a moment."
    return "I'm having trouble searching my knowledge base right now. Please try again in a moment."


def build_route_fallback_text(*, route_kind: str, reason: str) -> str:
    route = str(route_kind or "").strip().lower()
    if route in {"detail_mode", "search_specific", "browse_products", "product"}:
        return "I can only provide a basic product result right now while search is temporarily limited."
    if route in {"knowledge_query", "rag_strict", "knowledge"}:
        return "I can share a brief answer right now, but detailed knowledge search is temporarily unavailable."
    if route in {"vague", "clarify"}:
        return "Could you share a bit more detail so I can narrow this down accurately?"
    if reason == "external_call_budget":
        return "I reached my call budget for this request. Please try a shorter follow-up."
    return "I'm having trouble completing that request right now. Please try again in a moment."


async def build_embedding_fail_fast_response(
    *,
    service: Any,
    conversation_id: int,
    user_text: str,
    reply_language: str,
    target_currency: str,
    debug_meta: Dict[str, Any],
    use_products: bool,
    use_knowledge: bool,
) -> ChatResponse:
    reply_text = embedding_failure_reply_text(use_products=use_products, use_knowledge=use_knowledge)
    return await service._response_renderer.render(
        conversation_id=conversation_id,
        route="fallback_general",
        reply_data={
            "reply": reply_text,
            "carousel_hint": "",
            "recommended_questions": [],
        },
        product_carousel=[],
        follow_up_questions=[],
        sources=[],
        debug=debug_meta,
        reply_language=reply_language,
        target_currency=target_currency,
        user_text=user_text,
        apply_polish=False,
    )


async def build_route_fallback_response(
    *,
    service: Any,
    conversation_id: int,
    route_kind: str,
    reason: str,
    user_text: str,
    reply_language: str,
    target_currency: str,
    debug_meta: Dict[str, Any],
    product_carousel: Optional[List[ProductCard]] = None,
) -> ChatResponse:
    reply_text = build_route_fallback_text(route_kind=route_kind, reason=reason)
    follow_ups: List[str] = []
    if str(route_kind).lower() in {"vague", "clarify"}:
        follow_ups = ["Share product type, material, or SKU to continue."]
    return await service._response_renderer.render(
        conversation_id=conversation_id,
        route="fallback_general",
        reply_data={
            "reply": reply_text,
            "carousel_hint": "Limited product result shown." if product_carousel else "",
            "recommended_questions": follow_ups,
        },
        product_carousel=list(product_carousel or []),
        follow_up_questions=follow_ups,
        sources=[],
        debug=debug_meta,
        reply_language=reply_language,
        target_currency=target_currency,
        user_text=user_text,
        apply_polish=False,
    )


def build_product_list_filter_phrase(attribute_filters: Dict[str, str]) -> str:
    if not attribute_filters:
        return ""
    jewelry_type = str(attribute_filters.get("jewelry_type") or "").strip()
    material = str(attribute_filters.get("material") or "").strip()
    gauge = str(attribute_filters.get("gauge") or "").strip()
    color = str(attribute_filters.get("color") or "").strip()
    threading = str(attribute_filters.get("threading") or "").strip()

    parts: List[str] = []
    if jewelry_type:
        parts.append(f"{jewelry_type} items")
    if material:
        parts.append(f"in {material}")
    if gauge:
        parts.append(f"({gauge})")
    if color:
        parts.append(f"color {color}")
    if threading:
        parts.append(f"{threading} threading")
    return " ".join(parts).strip()


def build_deterministic_product_reply_data(
    *,
    products: List[ProductCard],
    attribute_filters: Dict[str, str],
) -> Dict[str, Any]:
    count = len(products)
    if count <= 0:
        return {"reply": "I couldn't find matching products right now.", "carousel_hint": "", "recommended_questions": []}

    if count == 1:
        product = products[0]
        product_name = str(product.name or product.sku or "item").strip()
        return {
            "reply": f"I found 1 matching product: {product_name} (SKU {product.sku}).",
            "carousel_hint": "Matching product is shown below.",
            "recommended_questions": [],
        }

    filter_phrase = build_product_list_filter_phrase(attribute_filters)
    if filter_phrase:
        reply = f"I found {count} matching products for {filter_phrase}. Showing top matches below."
    else:
        reply = f"I found {count} matching products. Showing top matches below."
    return {
        "reply": reply,
        "carousel_hint": "Matching products are shown below.",
        "recommended_questions": [],
    }
