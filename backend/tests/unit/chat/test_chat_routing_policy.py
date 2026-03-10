from app.services.chat.routing_policy import decide_route


def test_routing_policy_detects_store_overview() -> None:
    decision = decide_route(
        text="What do you have in your store?",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.intent == "browse_products"
    assert decision.store_overview_request is True
    assert decision.knowledge_intent is False


def test_routing_policy_detects_knowledge_query_without_product_signals() -> None:
    decision = decide_route(
        text="What is your return policy?",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.intent == "knowledge_query"
    assert decision.knowledge_intent is True


def test_routing_policy_detects_compare_request() -> None:
    decision = decide_route(
        text="Compare AAA-1 and BBB-2",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=["AAA-1", "BBB-2"],
    )

    assert decision.intent == "compare_products"
    assert decision.compare_requested is True
