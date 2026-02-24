import pytest

from app.services.chat.intent_router import IntentRouter
from app.services.chat.retrieval_gate import RetrievalGate


def _clean_code_candidate(value: str) -> str:
    return value.strip().strip(".,;:()[]{}")


def _extract_sku(text: str):
    if "SKU123" in text:
        return "SKU123"
    return None


def _looks_like_code(value: str) -> bool:
    return any(ch.isdigit() for ch in value)


@pytest.mark.regression
def test_intent_router_extracts_nlu_and_sku_signal() -> None:
    decision = IntentRouter.resolve(
        nlu_data={
            "intent": "search_specific",
            "show_products": False,
            "product_code": " SKU123 ",
            "refined_query": "SKU123",
        },
        user_text="do you have SKU123?",
        clean_code_candidate=_clean_code_candidate,
        extract_sku=_extract_sku,
        looks_like_code=_looks_like_code,
    )

    assert decision.intent == "search_specific"
    assert decision.search_query == "SKU123"
    assert decision.sku_token == "SKU123"
    assert decision.is_product_intent is True


@pytest.mark.regression
@pytest.mark.parametrize(
    "intent,show_products,sku_token,expected_products,expected_knowledge",
    [
        ("browse_products", True, None, True, False),
        ("search_specific", False, None, True, False),
        ("knowledge_query", False, None, False, True),
        ("off_topic", False, None, False, True),
    ],
)
def test_retrieval_gate_intent_matrix(
    intent: str,
    show_products: bool,
    sku_token: str | None,
    expected_products: bool,
    expected_knowledge: bool,
) -> None:
    decision = RetrievalGate.decide(
        intent=intent,
        show_products_flag=show_products,
        is_product_intent=intent in {"browse_products", "search_specific"},
        sku_token=sku_token,
        user_text="hello",
        infer_jewelry_type_filter=lambda _: None,
        is_question_like_fn=lambda _: False,
        is_complex_query_fn=lambda _: False,
        count_policy_topics_fn=lambda _: 0,
    )

    assert decision.use_products is expected_products
    assert decision.use_knowledge is expected_knowledge
