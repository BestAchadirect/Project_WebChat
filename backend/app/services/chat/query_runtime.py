from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger
from app.models.product import Product
from app.prompts.system_prompts import rag_answer_prompt
from app.schemas.chat import KnowledgeSource, ProductCard
from app.services.ai.llm_service import llm_service
from app.utils.debug_log import debug_log as _debug_log

logger = get_logger(__name__)


def product_to_card(*, service: Any, product: Product, eav_attrs: Optional[Dict[str, Any]] = None) -> ProductCard:
    attrs = service._merge_product_attrs(product.attributes, eav_attrs)
    search_text = str(getattr(product, "search_text", "") or "").lower()

    if not str(attrs.get("material") or "").strip():
        inferred_material = service._catalog_search._infer_from_search_text(
            search_text=search_text,
            token_map=service._catalog_search._MATERIAL_FALLBACK_TOKENS,
        )
        if inferred_material:
            attrs["material"] = inferred_material

    if not str(attrs.get("jewelry_type") or attrs.get("type") or "").strip():
        inferred_type = service._catalog_search._infer_from_search_text(
            search_text=search_text,
            token_map=service._catalog_search._JEWELRY_TYPE_FALLBACK_TOKENS,
        )
        if inferred_type:
            attrs["jewelry_type"] = inferred_type

    return ProductCard(
        id=product.id,
        object_id=product.object_id,
        sku=product.sku,
        legacy_sku=product.legacy_sku or [],
        name=product.name,
        description=product.description,
        price=product.price,
        currency=product.currency,
        stock_status=product.stock_status,
        image_url=product.image_url,
        product_url=product.product_url,
        attributes=attrs,
    )


async def search_products(
    *,
    service: Any,
    query_embedding: List[float],
    limit: int = 10,
    run_id: Optional[str] = None,
) -> Tuple[List[ProductCard], List[float], Optional[float], Dict[str, float]]:
    candidate_multiplier = max(1, int(getattr(settings, "PRODUCT_SEARCH_CANDIDATE_MULTIPLIER", 3)))
    result = await service._catalog_search.vector_search(
        query_embedding=query_embedding,
        limit=limit,
        candidate_multiplier=candidate_multiplier,
    )
    product_cards = result.cards
    distance_by_id = result.distance_by_id
    best_distance = result.best_distance
    distances = result.distances

    for idx, card in enumerate(product_cards[:3]):
        distance = distance_by_id.get(str(card.id))
        if run_id and distance is not None:
            try:
                _debug_log(
                    {
                        "sessionId": "debug-session",
                        "runId": run_id,
                        "hypothesisId": "HP",
                        "location": "chat_service.search_products:top_result",
                        "message": "top product",
                        "data": {
                            "rank": idx + 1,
                            "product_id": str(card.id),
                            "name": card.name,
                            "distance": float(distance),
                            "threshold": settings.PRODUCT_DISTANCE_THRESHOLD,
                        },
                        "timestamp": int(time.time() * 1000),
                    }
                )
            except Exception:
                pass

    return product_cards, distances, best_distance, distance_by_id


async def synthesize_answer(
    *,
    service: Any,
    question: str,
    sources: List[KnowledgeSource],
    reply_language: str,
    history: List[Dict[str, str]] = None,
    run_id: Optional[str] = None,
) -> Dict[str, str]:
    if not sources:
        msg = await service._localize_ui_text(
            reply_language=reply_language,
            text=(
                "I don't have enough information in my knowledge base to answer that yet. "
                "Try asking another question or rephrasing."
            ),
            run_id=run_id or "synthesize_answer",
        )
        return {"reply": msg, "carousel_hint": ""}

    product_context = []
    if history:
        for msg in reversed(history):
            if msg.get("role") == "assistant" and msg.get("product_data"):
                products = msg["product_data"]
                summary = ", ".join([f"{p.get('name')} (SKU: {p.get('sku')})" for p in products[:5]])
                product_context.append(f"Previously shown products: {summary}")

    history_snippets = "\n".join(product_context)

    context = "\n\n".join(
        [
            f"ID: {s.source_id}\nTITLE: {s.title}\nTEXT: {s.content_snippet}"
            for s in sources[: min(5, len(sources))]
        ]
    )

    if history_snippets:
        context = f"History Context:\n{history_snippets}\n\nSearch Context:\n{context}"
    messages = [
        {
            "role": "system",
            "content": rag_answer_prompt(reply_language),
        },
    ]

    if history:
        history_clean = [{"role": m["role"], "content": m["content"]} for m in history]
        messages.extend(history_clean)

    messages.append({"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"})
    try:
        answer_model = getattr(settings, "RAG_ANSWER_MODEL", None) or settings.OPENAI_MODEL
        data = await llm_service.generate_chat_json(
            messages,
            model=answer_model,
            temperature=0.2,
            usage_kind="rag_answer",
        )
        return {
            "reply": str(data.get("reply", "")),
            "carousel_hint": str(data.get("carousel_hint", "")),
            "recommended_questions": data.get("recommended_questions", []),
        }
    except Exception as e:
        logger.error(f"LLM response generation failed: {e}")
        msg = await service._localize_ui_text(
            reply_language=reply_language,
            text="I'm having trouble generating an answer right now. Please try again.",
            run_id=run_id or "synthesize_answer",
        )
        return {"reply": msg, "carousel_hint": "", "recommended_questions": []}
