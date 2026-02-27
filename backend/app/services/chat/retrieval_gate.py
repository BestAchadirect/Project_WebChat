from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class RetrievalDecision:
    use_products: bool
    use_knowledge: bool
    is_question_like: bool
    is_complex: bool
    policy_topic_count: int
    is_policy_intent: bool
    looks_like_product: bool


class RetrievalGate:
    @staticmethod
    def decide(
        *,
        intent: str,
        show_products_flag: bool,
        is_product_intent: bool,
        sku_token: Optional[str],
        has_attribute_filters: bool = False,
        detail_request: bool = False,
        user_text: str,
        infer_jewelry_type_filter: Callable[[str], Optional[str]],
        is_question_like_fn: Callable[[str], bool],
        is_complex_query_fn: Callable[[str], bool],
        count_policy_topics_fn: Callable[[str], int],
    ) -> RetrievalDecision:
        explicit_product_signal = bool(
            sku_token or has_attribute_filters or detail_request or infer_jewelry_type_filter(user_text)
        )

        if intent == "off_topic":
            use_knowledge = True
            use_products = explicit_product_signal
        elif intent == "knowledge_query":
            use_knowledge = True
            use_products = explicit_product_signal
        elif intent in {"browse_products", "search_specific"}:
            use_products = True
            use_knowledge = False
        else:
            use_products = False
            use_knowledge = False

        is_question_like = is_question_like_fn(user_text)
        is_complex = is_complex_query_fn(user_text)
        policy_topic_count = count_policy_topics_fn(user_text)
        is_policy_intent = intent == "knowledge_query" and policy_topic_count > 0
        looks_like_product = bool(
            infer_jewelry_type_filter(user_text) or sku_token or is_product_intent
        )

        return RetrievalDecision(
            use_products=use_products,
            use_knowledge=use_knowledge,
            is_question_like=is_question_like,
            is_complex=is_complex,
            policy_topic_count=policy_topic_count,
            is_policy_intent=is_policy_intent,
            looks_like_product=looks_like_product,
        )
