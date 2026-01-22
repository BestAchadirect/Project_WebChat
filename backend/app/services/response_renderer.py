from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.schemas.chat import ChatResponse, KnowledgeSource, ProductCard
from app.services.answer_polisher import answer_polisher
from app.services.currency_service import currency_service
from app.services.llm_service import llm_service


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
        reply_data: Dict[str, str],
        product_carousel: List[ProductCard],
        follow_up_questions: List[str],
        sources: List[KnowledgeSource],
        debug: Dict[str, Any],
        reply_language: Optional[str] = None,
        target_currency: str,
        user_text: str,
        apply_polish: bool,
    ) -> ChatResponse:
        reply_text = reply_data.get("reply", "")
        carousel_msg = reply_data.get("carousel_hint", "")

        text = self._strip_sources_block(reply_text)
        if product_carousel:
            product_carousel = currency_service.convert_product_cards(product_carousel, to_currency=target_currency)

        # Selective Multi-language Support
        button_text = "View Product Details"
        material_label = "Material"
        jewelry_type_label = "Jewelry Type"
        
        is_english = not reply_language or reply_language.lower().startswith("en") or "english" in reply_language.lower()
        
        if not is_english and product_carousel:
            # 1. Translate descriptions and attribute values in batch
            to_translate = []
            for p in product_carousel:
                if p.description:
                    to_translate.append(p.description)
                if p.attributes.get("material"):
                    to_translate.append(str(p.attributes["material"]))
                if p.attributes.get("jewelry_type"):
                    to_translate.append(str(p.attributes["jewelry_type"]))

            if to_translate:
                translated = await llm_service.translate_product_descriptions(
                    descriptions=to_translate,
                    reply_language=reply_language
                )
                
                # Map back
                idx = 0
                for p in product_carousel:
                    if p.description:
                        if idx < len(translated):
                            p.description = translated[idx]
                            idx += 1
                    if p.attributes.get("material"):
                        if idx < len(translated):
                            p.attributes["material"] = translated[idx]
                            idx += 1
                    if p.attributes.get("jewelry_type"):
                        if idx < len(translated):
                            p.attributes["jewelry_type"] = translated[idx]
                            idx += 1

            # 2. Localize UI labels
            localized_ui = await llm_service.localize_ui_strings(
                items={
                    "btn": button_text,
                    "mat": material_label,
                    "type": jewelry_type_label
                },
                reply_language=reply_language
            )
            button_text = localized_ui.get("btn", button_text)
            material_label = localized_ui.get("mat", material_label)
            jewelry_type_label = localized_ui.get("type", jewelry_type_label)
        
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
            carousel_msg=carousel_msg,
            product_carousel=product_carousel,
            follow_up_questions=follow_up_questions,
            intent=route,
            sources=sources,
            debug=debug,
            view_button_text=button_text,
            material_label=material_label,
            jewelry_type_label=jewelry_type_label,
        )
