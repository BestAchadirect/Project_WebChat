from app.services.chat.result_policy import classify_match_tier, semantic_fallback_decision


def test_result_policy_blocks_semantic_fallback_for_detail_mode() -> None:
    decision = semantic_fallback_decision(
        intent="browse_products",
        attribute_filters={},
        sku_tokens=[],
        detail_mode=True,
        compare_requested=False,
        store_overview_request=False,
    )

    assert decision.allow is False
    assert decision.reason == "detail_mode"


def test_result_policy_allows_semantic_fallback_for_discovery_query() -> None:
    decision = semantic_fallback_decision(
        intent="recommend_products",
        attribute_filters={},
        sku_tokens=[],
        detail_mode=False,
        compare_requested=False,
        store_overview_request=False,
    )

    assert decision.allow is True
    assert decision.reason == "discovery_query"


def test_result_policy_classifies_match_tiers() -> None:
    assert classify_match_tier(structured_found=True, semantic_found=False) == "exact_match"
    assert classify_match_tier(structured_found=False, semantic_found=True) == "semantic_suggestion"
    assert classify_match_tier(structured_found=False, semantic_found=False) == "no_match"
