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


def test_apply_soft_hint_gate_requires_all_soft_filters() -> None:
    matching = SimpleNamespace(attributes={"finish": "sterilized", "color": "opal"})
    partial = SimpleNamespace(attributes={"finish": "sterilized", "color": "black"})

    cards, meta = ComponentPipeline._apply_soft_hint_gate(
        cards=[matching, partial],
        soft_filters={"finish": "sterilized", "color": "opal"},
    )

    assert cards == [matching]
    assert meta["semantic_soft_constraint_keys"] == ["finish", "color"]
    assert meta["semantic_soft_constraint_match_count"] == 1
    assert meta["semantic_soft_constraint_rejection_reason"] == ""


def test_apply_soft_hint_gate_reports_no_match() -> None:
    broad = SimpleNamespace(attributes={"color": "opal"})

    cards, meta = ComponentPipeline._apply_soft_hint_gate(
        cards=[broad],
        soft_filters={"finish": "sterilized", "color": "opal"},
    )

    assert cards == []
    assert meta["semantic_soft_constraint_match_count"] == 0
    assert meta["semantic_soft_constraint_rejection_reason"] == "soft_constraint_no_match"


def test_build_clarify_policy_soft_constraint_mismatch_mentions_filters() -> None:
    result = ComponentPipeline._build_clarify_policy(
        reason="soft_constraint_mismatch",
        user_text="Do you have sterilization with opal?",
        tone_pick=lambda _key, variants: variants[0],
        products=[],
        attribute_filters={"finish": "sterilized", "color": "opal"},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert result["reason"] == "soft_constraint_mismatch"
    assert "sterilized finish" in result["message"]
    assert "opal color" in result["message"]
