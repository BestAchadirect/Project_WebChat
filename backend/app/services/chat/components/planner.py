from __future__ import annotations

from typing import List

from app.services.chat.components.types import ComponentType


class OutputPlanner:
    @staticmethod
    def _normalized(text: str) -> str:
        return " ".join(str(text or "").strip().lower().split())

    @classmethod
    def plan(
        cls,
        *,
        user_text: str,
        intent: str,
        sku_count: int,
        product_count: int,
        is_detail_mode: bool,
        is_ambiguous: bool,
        ambiguity_reason: str | None = None,
    ) -> List[ComponentType]:
        text = cls._normalized(user_text)
        intent_norm = cls._normalized(intent)

        if not text:
            return [ComponentType.ERROR]

        if is_ambiguous:
            return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]

        if intent_norm in {"knowledge_query", "knowledge", "faq", "off_topic"}:
            return [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]

        if "compare" in text:
            return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]

        wants_reco = any(token in text for token in ("suggest", "recommend", "minimal"))

        components: List[ComponentType] = [ComponentType.QUERY_SUMMARY]

        product_intent = intent_norm.startswith("product") or intent_norm in {"browse_products", "search_specific"}
        if product_count <= 0 and product_intent:
            return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
        components.append(ComponentType.PRODUCT_CARDS)

        if wants_reco:
            components.append(ComponentType.RECOMMENDATIONS)

        deduped: List[ComponentType] = []
        seen = set()
        for item in components:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped
