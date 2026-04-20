from types import SimpleNamespace

import pytest

from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.presentation import clarify_policy


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


@pytest.mark.asyncio
async def test_build_clarify_policy_semantic_concept_unclear_uses_focus_specific_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_contextual_reply(*, kind, reply_language, payload):
        assert kind == "clarify"
        assert payload.get("clarify_focus") == "condition"
        assert payload.get("clarify_instruction")
        assert payload.get("clarify_question") == "What condition are you looking for?"
        assert "suggested_examples" not in payload
        return "What condition are you looking for?"

    monkeypatch.setattr(clarify_policy, "generate_contextual_reply", fake_generate_contextual_reply)

    result = await ComponentPipeline._build_clarify_policy(
        reason="semantic_concept_unclear",
        clarify_focus="condition",
        user_text="I want to buy sterilization product",
        reply_language="en-US",
        products=[],
        attribute_filters={},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert result["reason"] == "semantic_concept_unclear"
    assert result["message"] == "What condition are you looking for?"
    assert result["questions"] == []
    assert result["suggestions"] == []
    assert result["extra_debug"]["clarify_mode"] == "strict_ambiguity"
    assert result["extra_debug"]["clarify_best_effort_help"] is False


@pytest.mark.asyncio
async def test_build_clarify_policy_structured_no_match_is_best_effort_helpful() -> None:
    result = await ComponentPipeline._build_clarify_policy(
        reason="structured_no_match",
        user_text="show me something elegant for helix",
        reply_language="en-US",
        products=[],
        attribute_filters={},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert result["reason"] == "structured_no_match"
    assert "material" in result["message"].lower() or "style" in result["message"].lower() or "gauge" in result["message"].lower()
    assert result["questions"] == ["Which detail should I use to continue?"]
    assert result["extra_debug"]["clarify_mode"] == "recoverable_product"
    assert result["extra_debug"]["clarify_best_effort_help"] is True


@pytest.mark.asyncio
async def test_build_clarify_policy_knowledge_unavailable_uses_contact_focus_followups() -> None:
    result = await ComponentPipeline._build_clarify_policy(
        reason="knowledge_unavailable",
        user_text="How can I contact your sales team?",
        reply_language="en-US",
        products=[],
        attribute_filters={},
        needs_knowledge=True,
        requested_fields=[],
    )

    assert result["reason"] == "knowledge_unavailable"
    assert result["questions"] == ["Do you need our sales email, phone number, or showroom address?"]
    assert result["suggestions"] == [
        "What is your sales email?",
        "What is your phone number?",
        "What is your showroom address?",
    ]
    assert result["extra_debug"]["knowledge_clarify_focus"] == "contact"
    assert result["extra_debug"]["clarify_mode"] == "strict_knowledge"
    assert result["extra_debug"]["clarify_best_effort_help"] is True
