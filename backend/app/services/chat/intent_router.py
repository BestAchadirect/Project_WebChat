from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    search_query: str
    show_products_flag: bool
    nlu_product_code: str
    sku_token: Optional[str]
    is_product_intent: bool


class IntentRouter:
    @staticmethod
    def resolve(
        *,
        nlu_data: Dict[str, Any],
        user_text: str,
        clean_code_candidate: Callable[[str], str],
        extract_sku: Callable[[str], Optional[str]],
        looks_like_code: Callable[[str], bool],
    ) -> IntentDecision:
        search_query = str(nlu_data.get("refined_query") or user_text or "").strip() or user_text or ""
        intent = str(nlu_data.get("intent") or "knowledge_query").strip().lower()
        show_products_flag = bool(nlu_data.get("show_products", False))
        nlu_product_code = clean_code_candidate(str(nlu_data.get("product_code") or "").strip())

        sku_token = extract_sku(user_text or "")
        if nlu_product_code and looks_like_code(nlu_product_code):
            sku_token = sku_token or nlu_product_code

        is_product_intent = intent in {"browse_products", "search_specific"} or show_products_flag
        if sku_token:
            is_product_intent = True

        return IntentDecision(
            intent=intent,
            search_query=search_query,
            show_products_flag=show_products_flag,
            nlu_product_code=nlu_product_code,
            sku_token=sku_token,
            is_product_intent=is_product_intent,
        )
