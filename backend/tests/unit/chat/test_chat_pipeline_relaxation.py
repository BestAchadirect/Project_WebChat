from types import SimpleNamespace

import pytest

from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.pipeline_runtime.workflow_handlers import PipelineWorkflowHandlersMixin
from app.services.chat.presentation import clarify_policy
from app.services.chat.components.pipeline_runtime import workflow_handlers


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
async def test_build_clarify_policy_pending_task_missing_slot_stays_product_focused() -> None:
    result = await ComponentPipeline._build_clarify_policy(
        reason="pending_task_missing_slot",
        user_text="what size and color is available for code ulbcvin?",
        reply_language="en-US",
        products=[],
        attribute_filters={},
        needs_knowledge=False,
        requested_fields=["size", "color"],
        clarify_question="Which product are you asking about?",
    )

    assert result["reason"] == "pending_task_missing_slot"
    assert result["message"] == "Which product are you asking about?"
    assert result["questions"] == ["Which product are you asking about?"]
    assert result["suggestions"] == [
        "Share the product code",
        "Tell me the material",
        "Tell me the product type",
    ]
    assert result["extra_debug"]["clarify_mode"] == "pending_task"


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
async def test_build_clarify_policy_grounding_no_match_is_evidence_bound() -> None:
    result = await ComponentPipeline._build_clarify_policy(
        reason="grounding_no_match",
        user_text="show products with opal color",
        reply_language="en-US",
        products=[],
        attribute_filters={"opal_color": "opal"},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert result["reason"] == "grounding_no_match"
    assert "couldn't find products" in result["message"].lower()
    assert "opal color" in result["message"].lower()
    assert "which product type" in result["questions"][0].lower()
    assert result["extra_debug"]["clarify_mode"] == "strict_grounding"
    assert result["extra_debug"]["clarify_category"] == "product_grounding"
    assert result["extra_debug"]["grounding_clarify_copy"] is True


@pytest.mark.asyncio
async def test_build_clarify_policy_grounding_needs_clarification_avoids_claiming_match() -> None:
    result = await ComponentPipeline._build_clarify_policy(
        reason="grounding_needs_clarification",
        user_text="show sterilization products",
        reply_language="en-US",
        products=[],
        attribute_filters={},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert result["reason"] == "grounding_needs_clarification"
    assert "couldn't confirm" in result["message"].lower()
    assert "which detail matters" in result["questions"][0].lower()
    assert result["extra_debug"]["clarify_mode"] == "strict_grounding"
    assert result["extra_debug"]["clarify_category"] == "product_grounding"


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
    assert result["extra_debug"]["clarify_category"] == "knowledge_unavailable"
    assert result["extra_debug"]["clarify_mode"] == "strict_knowledge"
    assert result["extra_debug"]["clarify_best_effort_help"] is True


@pytest.mark.asyncio
async def test_build_clarify_policy_knowledge_clarification_prefers_llm_question() -> None:
    question = "Which product or SKU are you asking about?"

    result = await ComponentPipeline._build_clarify_policy(
        reason="knowledge_needs_clarification",
        user_text="So is the product from China or made in Thailand?",
        reply_language="en-US",
        products=[],
        attribute_filters={},
        needs_knowledge=True,
        requested_fields=[],
        clarify_question=question,
    )

    assert result["reason"] == "knowledge_needs_clarification"
    assert result["questions"] == [question]
    assert result["extra_debug"]["knowledge_clarify_focus"] == "general"


@pytest.mark.asyncio
async def test_build_clarify_policy_fallback_vague_store_request_uses_broad_scope_prompt() -> None:
    result = await ComponentPipeline._build_clarify_policy(
        reason="fallback_vague_store_request",
        user_text="help me",
        reply_language="en-US",
        products=[],
        attribute_filters={},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert result["reason"] == "fallback_vague_store_request"
    assert result["message"].strip()
    assert result["questions"] == ["What do you want help with right now?"]
    assert result["extra_debug"]["clarify_category"] == "vague_store_request"
    assert result["extra_debug"]["clarify_mode"] == "broad_help"


@pytest.mark.asyncio
async def test_terminal_workflow_uses_default_llm_copy_for_product_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_generate_contextual_reply(*, kind, reply_language, payload):
        captured["kind"] = kind
        captured["reply_language"] = reply_language
        captured["payload"] = payload
        return "I can help you find products by type, material, color, gauge, size, stock, price, or SKU."

    monkeypatch.setattr(workflow_handlers, "generate_contextual_reply", fake_generate_contextual_reply)

    state = PipelineWorkflowState()
    state.decision.intent = "product_information"
    state.decision.subintent = "product_capability"
    state.decision.response_policy = "answer_from_allowed_capabilities"
    handler = PipelineWorkflowHandlersMixin()
    handled, llm_calls = await handler._handle_terminal_workflows(
        state=state,
        text="what can you help me with the products?",
        locale="en-US",
        workflow="off_topic",
        internal_workflow="general_talking",
        debug_meta={},
        spans={"llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert handled is True
    assert llm_calls == 1
    assert captured["kind"] == "default"
    assert state.decision.intent == "product_information"


@pytest.mark.asyncio
async def test_terminal_workflow_blocks_retrieval_required_company_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_contextual_reply(*, kind, reply_language, payload):
        raise AssertionError("terminal LLM copy should not run for retrieval-required facts")

    monkeypatch.setattr(workflow_handlers, "generate_contextual_reply", fake_generate_contextual_reply)

    state = PipelineWorkflowState()
    state.decision.intent = "knowledge_policy"
    state.decision.response_policy = "answer_from_retrieved_data"
    handler = PipelineWorkflowHandlersMixin()
    debug_meta: dict[str, object] = {}
    handled, llm_calls = await handler._handle_terminal_workflows(
        state=state,
        text="How can I contact you?",
        locale="en-US",
        workflow="general_talking",
        internal_workflow="general_talking",
        debug_meta=debug_meta,
        spans={"llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert handled is True
    assert llm_calls == 0
    assert state.decision.ambiguity_reason == "knowledge_unavailable"
    assert debug_meta["terminal_reply_blocked_reason"] == "retrieval_required"


@pytest.mark.asyncio
async def test_build_clarify_policy_fallback_gibberish_requests_rephrase() -> None:
    result = await ComponentPipeline._build_clarify_policy(
        reason="fallback_gibberish",
        user_text="asdfafafdas",
        reply_language="en-US",
        products=[],
        attribute_filters={},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert result["reason"] == "fallback_gibberish"
    assert "rephrase" in result["message"].lower()
    assert result["questions"] == ["Can you rephrase your request?"]
    assert result["extra_debug"]["clarify_category"] == "gibberish_rephrase"
    assert result["extra_debug"]["clarify_mode"] == "gibberish"


@pytest.mark.asyncio
async def test_build_clarify_policy_fallback_off_topic_redirect_uses_scope_redirect_copy() -> None:
    result = await ComponentPipeline._build_clarify_policy(
        reason="fallback_off_topic_redirect",
        user_text="can you help with something else",
        reply_language="en-US",
        products=[],
        attribute_filters={},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert result["reason"] == "fallback_off_topic_redirect"
    assert "shopping" in result["message"].lower() or "store" in result["message"].lower()
    assert result["questions"] == ["Which store question do you want help with?"]
    assert result["extra_debug"]["clarify_category"] == "off_topic_redirect"
    assert result["extra_debug"]["clarify_mode"] == "scope_redirect"
