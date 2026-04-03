from app.services.chat.components.types import ComponentSource
from app.services.chat.retrieval.result_policy import classify_match_tier
from app.services.chat.retrieval.retrieval_outcome import build_retrieval_outcome


def test_result_policy_classifies_match_tiers() -> None:
    assert classify_match_tier(structured_found=True, semantic_found=False) == "exact_match"
    assert classify_match_tier(structured_found=False, semantic_found=True) == "semantic_suggestion"
    assert classify_match_tier(structured_found=False, semantic_found=False) == "no_match"


def test_retrieval_outcome_distinguishes_exact_semantic_and_clarify_paths() -> None:
    exact = build_retrieval_outcome(
        retrieval_source=ComponentSource.SQL,
        product_ids=["1"],
        ambiguity_reason="",
    )
    semantic = build_retrieval_outcome(
        retrieval_source=ComponentSource.VECTOR,
        product_ids=["1"],
        ambiguity_reason="",
    )
    clarify = build_retrieval_outcome(
        retrieval_source=ComponentSource.ERROR,
        product_ids=[],
        ambiguity_reason="structured_no_match",
    )

    assert exact.is_exact_match is True
    assert exact.is_semantic_fallback is False
    assert exact.needs_clarification is False
    assert exact.retrieval_quality == "exact"
    assert semantic.is_exact_match is False
    assert semantic.is_semantic_fallback is True
    assert semantic.needs_clarification is False
    assert semantic.retrieval_quality == "approximate"
    assert clarify.match_tier == "no_match"
    assert clarify.is_exact_match is False
    assert clarify.is_semantic_fallback is False
    assert clarify.needs_clarification is True
    assert clarify.retrieval_quality == "no_match"
