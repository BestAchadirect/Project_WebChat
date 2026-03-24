from app.services.chat.retrieval.result_policy import classify_match_tier


def test_result_policy_classifies_match_tiers() -> None:
    assert classify_match_tier(structured_found=True, semantic_found=False) == "exact_match"
    assert classify_match_tier(structured_found=False, semantic_found=True) == "semantic_suggestion"
    assert classify_match_tier(structured_found=False, semantic_found=False) == "no_match"
