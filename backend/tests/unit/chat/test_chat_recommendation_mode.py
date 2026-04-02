from app.services.chat.retrieval.recommendation_service import RecommendationService


def test_resolve_mode_respects_valid_requested_mode() -> None:
    assert RecommendationService.resolve_mode(requested_mode="complementary_items") == "complementary_items"


def test_resolve_mode_prefers_complementary_for_matching_cue_and_anchor_products() -> None:
    assert RecommendationService.resolve_mode(
        user_text="what goes with this?",
        anchor_products=[object()],
    ) == "complementary_items"


def test_resolve_mode_defaults_to_similar_when_no_complementary_signal_exists() -> None:
    assert RecommendationService.resolve_mode(user_text="show me more like this") == "similar_items"
