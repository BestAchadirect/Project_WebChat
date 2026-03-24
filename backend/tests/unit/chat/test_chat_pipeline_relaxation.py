from types import SimpleNamespace

from app.services.chat.components.pipeline import ComponentPipeline


def test_apply_hard_constraint_gate_keeps_only_matching_cards() -> None:
    matching = SimpleNamespace(attributes={"gauge": "14g", "material": "steel"})
    non_matching = SimpleNamespace(attributes={"gauge": "16g", "material": "steel"})

    cards, meta = ComponentPipeline._apply_hard_constraint_gate(
        cards=[matching, non_matching],
        hard_filters={"gauge": "14g"},
    )

    assert cards == [matching]
    assert meta["semantic_hard_constraint_keys"] == ["gauge"]
    assert meta["semantic_hard_constraint_match_count"] == 1
    assert meta["semantic_hard_constraint_rejection_reason"] == ""


def test_apply_soft_hint_gate_reranks_full_matches_first() -> None:
    matching = SimpleNamespace(attributes={"finish": "sterilized", "color": "opal"})
    partial = SimpleNamespace(attributes={"finish": "sterilized", "color": "black"})

    cards, meta = ComponentPipeline._apply_soft_hint_gate(
        cards=[matching, partial],
        soft_filters={"finish": "sterilized", "color": "opal"},
    )

    assert cards == [matching, partial]
    assert meta["semantic_soft_constraint_keys"] == ["finish", "color"]
    assert meta["semantic_soft_constraint_match_count"] == 1
    assert meta["semantic_soft_constraint_full_match_count"] == 1
    assert meta["semantic_soft_constraint_partial_match_count"] == 1
    assert meta["semantic_soft_constraint_rank_applied"] is True
    assert meta["semantic_soft_constraint_rejection_reason"] == ""


def test_apply_soft_hint_gate_keeps_partial_matches_when_no_full_match_exists() -> None:
    broad = SimpleNamespace(attributes={"color": "opal"})

    cards, meta = ComponentPipeline._apply_soft_hint_gate(
        cards=[broad],
        soft_filters={"finish": "sterilized", "color": "opal"},
    )

    assert cards == [broad]
    assert meta["semantic_soft_constraint_match_count"] == 0
    assert meta["semantic_soft_constraint_full_match_count"] == 0
    assert meta["semantic_soft_constraint_partial_match_count"] == 1
    assert meta["semantic_soft_constraint_rank_applied"] is True
    assert meta["semantic_soft_constraint_rejection_reason"] == ""


def test_build_clarify_policy_semantic_concept_unclear_uses_focus_specific_copy() -> None:
    result = ComponentPipeline._build_clarify_policy(
        reason="semantic_concept_unclear",
        clarify_focus="sterilization_meaning",
        user_text="I want to buy sterilization product",
        tone_pick=lambda _key, variants: variants[0],
        products=[],
        attribute_filters={},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert result["reason"] == "semantic_concept_unclear"
    assert "pre-sterilized jewelry" in result["message"]
    assert "surgical steel jewelry" in result["message"]
