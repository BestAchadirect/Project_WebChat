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
            if sku_count < 2:
                return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
            return [ComponentType.QUERY_SUMMARY, ComponentType.COMPARE, ComponentType.RESULT_COUNT]

        wants_table = any(token in text for token in (" table", "grid", "spreadsheet", "show table")) or text.startswith("table")
        wants_bullets = any(token in text for token in ("bullet", "list briefly", "short list"))
        wants_count = any(token in text for token in ("how many", "count", "number of"))
        wants_reco = any(token in text for token in ("suggest", "recommend", "minimal"))

        components: List[ComponentType] = [ComponentType.QUERY_SUMMARY]

        product_intent = intent_norm.startswith("product") or intent_norm in {"browse_products", "search_specific"}
        if product_count <= 0 and product_intent:
            return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]

        if is_detail_mode or (sku_count == 1 and product_count == 1):
            components.append(ComponentType.PRODUCT_DETAIL)
        elif wants_table:
            components.extend([ComponentType.RESULT_COUNT, ComponentType.PRODUCT_TABLE])
        elif wants_bullets:
            components.extend([ComponentType.RESULT_COUNT, ComponentType.PRODUCT_BULLETS])
        else:
            components.extend([ComponentType.RESULT_COUNT, ComponentType.PRODUCT_CARDS])

        if wants_count and ComponentType.RESULT_COUNT not in components:
            components.append(ComponentType.RESULT_COUNT)

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
