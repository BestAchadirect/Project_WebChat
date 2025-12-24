from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.schemas.chat import ChatResponse, KnowledgeSource, ProductCard
from app.services.answer_polisher import answer_polisher
from app.services.currency_service import currency_service


class ResponseRenderer:
    def _strip_sources_block(self, text: str) -> str:
        if not text:
            return text
        lowered = text.lower()
        markers = ["\n\nsources:\n", "\nsources:\n", "\n\nreferences:\n", "\nreferences:\n"]
        for marker in markers:
            idx = lowered.find(marker.strip("\n"))
            if idx != -1:
                return text[:idx].rstrip()
        return text

    async def render(
        self,
        *,
        conversation_id: int,
        route: str,
        reply_text: str,
        product_carousel: List[ProductCard],
        follow_up_questions: List[str],
        sources: List[KnowledgeSource],
        debug: Dict[str, Any],
        reply_language: Optional[str] = None,
        target_currency: str,
        user_text: str,
        apply_polish: bool,
    ) -> ChatResponse:
        text = self._strip_sources_block(reply_text)
        if product_carousel:
            product_carousel = currency_service.convert_product_cards(product_carousel, to_currency=target_currency)
        if apply_polish and route not in {"smalltalk", "product"}:
            text = await answer_polisher.polish(
                draft_text=text,
                route=route,
                user_text=user_text,
                has_product_carousel=bool(product_carousel),
                reply_language=reply_language,
            )
            text = self._strip_sources_block(text)

        return ChatResponse(
            conversation_id=conversation_id,
            reply_text=text,
            product_carousel=product_carousel,
            follow_up_questions=follow_up_questions,
            intent=route,
            sources=sources,
            debug=debug,
        )
