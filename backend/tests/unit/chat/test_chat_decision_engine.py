from __future__ import annotations

import pytest

from app.core.config import settings
from app.prompts.routing import understanding_workflow_prompt
from app.services.ai.llm_service import llm_service
from app.services.chat.routing.decision_engine import build_decision_state
from app.services.chat.routing.signals import classify_fallback_reason
from app.services.chat.routing.contracts import UnderstandingResult
from app.services.chat.routing.understanding import build_understanding_result


def _llm_payload(
    workflow_hypothesis: str,
    *,
    reason: str,
    confidence: float = 0.9,
    needs_products: bool = False,
    needs_knowledge: bool = False,
    knowledge_query: str = "",
    store_overview_request: bool = False,
    **hints,
) -> dict:
    return {
        "workflow_hypothesis": workflow_hypothesis,
        "needs_products": needs_products,
        "needs_knowledge": needs_knowledge,
        "store_overview_request": store_overview_request,
        "knowledge_query": knowledge_query,
        "reason": reason,
        "confidence": confidence,
        **hints,
    }


def _patch_understanding_llm(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    async def fake_generate_chat_json(*args, **kwargs):
        assert kwargs.get("usage_kind") == "chat_understanding"
        return dict(payload)

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)


async def _understanding(text: str):
    return await build_understanding_result(
        user_text=text,
        locale="en-US",
        channel="widget",
    )

@pytest.mark.asyncio
async def test_decision_engine_projects_company_info_to_public_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_understanding_llm(
        monkeypatch,
        _llm_payload(
            "company_info",
            reason="company question",
            needs_knowledge=True,
            knowledge_query="where is your company located",
            store_overview_request=True,
        ),
    )
    understanding = await _understanding("Where is the company?")
    decision = build_decision_state(
        understanding=understanding,
        user_text="Where is the company?",
        channel="widget",
    )

    assert decision.internal_workflow == "company_info"
    assert decision.public_workflow == "knowledge"
    assert decision.route_decision is not None
    assert decision.route_decision.workflow == "knowledge"
    assert decision.route_decision.knowledge_query == "where is your company located"
    assert decision.answerability == "none"


@pytest.mark.asyncio
async def test_decision_engine_projects_mixed_to_public_catalog_with_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_understanding_llm(
        monkeypatch,
        _llm_payload(
            "mixed",
            reason="mixed product and payment",
            needs_products=True,
            needs_knowledge=True,
            knowledge_query="what payment methods do you accept?",
        ),
    )
    understanding = await _understanding("Show me titanium jewelry and what payment methods do you accept?")
    decision = build_decision_state(
        understanding=understanding,
        user_text="Show me titanium jewelry and what payment methods do you accept?",
        channel="widget",
    )

    assert decision.internal_workflow == "mixed"
    assert decision.public_workflow == "catalog"
    assert decision.route_decision is not None
    assert decision.route_decision.needs_products is True
    assert decision.route_decision.needs_knowledge is True
    assert decision.route_decision.knowledge_query != ""


@pytest.mark.asyncio
async def test_decision_engine_keeps_clarify_as_public_fallback() -> None:
    understanding = await _understanding("")
    decision = build_decision_state(
        understanding=understanding,
        user_text="",
        channel="widget",
    )

    assert decision.internal_workflow == "clarify"
    assert decision.public_workflow == "fallback"
    assert decision.route_decision is not None
    assert decision.route_decision.reason == "fallback_missing_signal"
    assert decision.route_decision.needs_clarification is True
    assert decision.answerability == "none"


def test_decision_engine_uses_routing_fallback_for_understanding_failures() -> None:
    understanding = UnderstandingResult(
        normalized_text="weird question",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="clarify",
        intent_confidence=0.0,
        reason="routing_fallback",
        failure_reason="understanding_failed:runtimeerror",
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="weird question",
        channel="widget",
    )

    assert decision.public_workflow == "fallback"
    assert decision.route_decision is not None
    assert decision.route_decision.reason == "routing_fallback"
    assert decision.failure_reason == "understanding_failed:runtimeerror"


def test_decision_engine_segments_vague_store_fallback_reason() -> None:
    understanding = UnderstandingResult(
        normalized_text="help me",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="clarify",
        intent_confidence=0.25,
        reason="clarify",
        failure_reason="",
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="help me",
        channel="widget",
    )

    assert decision.public_workflow == "fallback"
    assert decision.route_decision is not None
    assert decision.route_decision.reason == "fallback_vague_store_request"


def test_decision_engine_segments_gibberish_fallback_reason() -> None:
    understanding = UnderstandingResult(
        normalized_text="asdfafafdas",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="clarify",
        intent_confidence=0.18,
        reason="clarify",
        failure_reason="",
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="asdfafafdas",
        channel="widget",
    )

    assert decision.public_workflow == "fallback"
    assert decision.route_decision is not None
    assert decision.route_decision.reason == "fallback_gibberish"


def test_decision_engine_preserves_explicit_off_topic_fallback_reason() -> None:
    understanding = UnderstandingResult(
        normalized_text="tell me about your store",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="clarify",
        intent_confidence=0.2,
        reason="fallback_off_topic_redirect",
        failure_reason="",
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="tell me about your store",
        channel="widget",
    )

    assert decision.public_workflow == "fallback"
    assert decision.route_decision is not None
    assert decision.route_decision.reason == "fallback_off_topic_redirect"


@pytest.mark.asyncio
async def test_decision_engine_prefers_agentic_for_supported_catalog_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")
    _patch_understanding_llm(
        monkeypatch,
        _llm_payload(
            "catalog_search",
            reason="product browse",
            needs_products=True,
        ),
    )

    understanding = await _understanding("show me titanium labrets")
    decision = build_decision_state(
        understanding=understanding,
        user_text="show me titanium labrets",
        channel="widget",
    )

    assert decision.public_workflow == "catalog"
    assert decision.execution_decision is not None
    assert decision.execution_decision.execution_mode == "agentic"
    assert decision.execution_decision.selection_source == "agentic"
    assert decision.execution_decision.tool_suitable is True


@pytest.mark.asyncio
async def test_decision_engine_prefers_agentic_for_supported_knowledge_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")
    _patch_understanding_llm(
        monkeypatch,
        _llm_payload(
            "policy_info",
            reason="policy question",
            needs_knowledge=True,
            knowledge_query="what is your shipping policy?",
        ),
    )

    understanding = await _understanding("What is your shipping policy?")
    decision = build_decision_state(
        understanding=understanding,
        user_text="What is your shipping policy?",
        channel="widget",
    )

    assert decision.public_workflow == "knowledge"
    assert decision.execution_decision is not None
    assert decision.execution_decision.execution_mode == "agentic"
    assert decision.execution_decision.selection_source == "agentic"
    assert decision.execution_decision.tool_suitable is True


def test_understanding_prompt_uses_response_intent_contract() -> None:
    prompt = understanding_workflow_prompt()

    assert "product_information" in prompt
    assert "knowledge_policy" in prompt
    assert "general_talking" in prompt
    assert "response_policy" in prompt
    assert "marketing assets" in prompt
    assert "stock or out-of-stock policy" in prompt
    assert "trust/references/compliance" in prompt
    assert "fallback" not in prompt


def test_decision_engine_routes_product_capability_intent_to_terminal_reply() -> None:
    understanding = UnderstandingResult(
        normalized_text="what can you help me with the products?",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="general_talking",
        intent_confidence=0.91,
        reason="product capability question",
        intent="product_information",
        subintent="product_capability",
        user_goal="User wants to know what product help is available.",
        response_policy="answer_from_allowed_capabilities",
        needs_products=False,
        needs_knowledge=False,
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="what can you help me with the products?",
        channel="widget",
    )

    assert decision.internal_workflow == "general_talking"
    assert decision.public_workflow == "general_talking"
    assert decision.route_decision is not None
    assert decision.route_decision.needs_clarification is False
    assert decision.response_policy == "answer_from_allowed_capabilities"


def test_decision_engine_routes_product_faq_intent_to_knowledge_when_retrieval_needed() -> None:
    understanding = UnderstandingResult(
        normalized_text="do you offer displays and boards?",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="general_talking",
        intent_confidence=0.88,
        reason="product FAQ question",
        intent="product_information",
        subintent="product_faq",
        user_goal="User wants to know whether the store offers displays and boards.",
        response_policy="answer_from_retrieved_data",
        product_query="",
        knowledge_query="do you offer displays and boards?",
        needs_products=False,
        needs_knowledge=True,
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="do you offer displays and boards?",
        channel="widget",
    )

    assert decision.internal_workflow == "policy_info"
    assert decision.public_workflow == "knowledge"
    assert decision.route_decision is not None
    assert decision.route_decision.workflow == "knowledge"
    assert decision.route_decision.needs_knowledge is True
    assert decision.route_decision.knowledge_query == "do you offer displays and boards?"


def test_decision_engine_keeps_store_policy_intent_on_policy_workflow() -> None:
    understanding = UnderstandingResult(
        normalized_text="what policy do you have in your store?",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="policy_info",
        intent_confidence=0.92,
        reason="store policy question",
        intent="knowledge_policy",
        subintent="store_policy",
        user_goal="User wants to know available store policies.",
        response_policy="answer_from_retrieved_data",
        knowledge_query="what store policies are available?",
        store_overview_request=True,
        needs_products=False,
        needs_knowledge=True,
        entity_hints={
            "has_company_signal": True,
            "has_policy_signal": True,
            "has_knowledge_signal": True,
            "preferred_knowledge_query": "what store policies are available?",
            "preferred_store_overview_request": True,
        },
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="what policy do you have in your store?",
        channel="widget",
    )

    assert decision.internal_workflow == "policy_info"
    assert decision.public_workflow == "knowledge"
    assert decision.route_decision is not None
    assert decision.route_decision.workflow == "knowledge"
    assert decision.route_decision.store_overview_request is False
    assert decision.route_decision.knowledge_query == "what store policies are available?"


def test_decision_engine_routes_contact_subintent_to_company_info() -> None:
    understanding = UnderstandingResult(
        normalized_text="i want to contact your sales team",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="policy_info",
        intent_confidence=0.91,
        reason="sales contact question",
        intent="knowledge_policy",
        subintent="sales_contact",
        user_goal="User wants sales contact details.",
        response_policy="answer_from_retrieved_data",
        knowledge_query="how can I contact sales?",
        store_overview_request=True,
        needs_products=False,
        needs_knowledge=True,
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="i want to contact your sales team",
        channel="widget",
    )

    assert decision.internal_workflow == "company_info"
    assert decision.public_workflow == "knowledge"
    assert decision.route_decision is not None
    assert decision.route_decision.store_overview_request is True


def test_decision_engine_routes_general_talking_contact_question_to_company_info() -> None:
    understanding = UnderstandingResult(
        normalized_text="how can i contact you",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="general_talking",
        intent_confidence=0.89,
        reason="contact question",
        intent="general_talking",
        subintent="contact",
        user_goal="User wants contact details.",
        response_policy="friendly_scoped_reply",
        knowledge_query="how can I contact you?",
        store_overview_request=False,
        needs_products=False,
        needs_knowledge=False,
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="how can i contact you",
        channel="widget",
    )

    assert decision.internal_workflow == "company_info"
    assert decision.public_workflow == "knowledge"
    assert decision.route_decision is not None
    assert decision.route_decision.workflow == "knowledge"


def test_decision_engine_routes_compound_company_subintent_to_company_info() -> None:
    understanding = UnderstandingResult(
        normalized_text="is your company in china or thailand?",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="policy_info",
        intent_confidence=0.86,
        reason="company location question",
        intent="knowledge_policy",
        subintent="company/contact/support",
        user_goal="User wants company location information.",
        response_policy="answer_from_retrieved_data",
        knowledge_query="Is your company located in China or Thailand?",
        store_overview_request=False,
        needs_products=False,
        needs_knowledge=True,
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="is your company in china or thailand?",
        channel="widget",
    )

    assert decision.internal_workflow == "company_info"
    assert decision.public_workflow == "knowledge"


def test_decision_engine_stores_resumable_clarify_reason() -> None:
    understanding = UnderstandingResult(
        normalized_text="is the product from china or made in thailand?",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="clarify",
        intent_confidence=0.9,
        reason="missing product anchor",
        intent="clarify",
        subintent="origin_question",
        user_goal="User wants product origin information.",
        response_policy="ask_clarifying_question",
        clarify_question="Which product are you asking about?",
        pending_task_type="product_origin_question",
        missing_slot="product_anchor",
        needs_products=False,
        needs_knowledge=False,
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="is the product from china or made in thailand?",
        channel="widget",
    )

    assert decision.public_workflow == "fallback"
    assert decision.route_decision is not None
    assert decision.route_decision.reason == "pending_task_missing_slot"
    assert decision.pending_task_type == "product_origin_question"
    assert decision.missing_slot == "product_anchor"


def test_decision_engine_can_project_from_entity_hints_without_workflow_ownership() -> None:
    understanding = UnderstandingResult(
        normalized_text="show me titanium labrets",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="clarify",
        intent_confidence=0.86,
        reason="catalog_signal_detected",
        entity_hints={
            "has_product_search_signal": True,
            "has_product_signal": True,
        },
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="show me titanium labrets",
        channel="widget",
    )

    assert decision.internal_workflow == "clarify"
    assert decision.public_workflow == "fallback"
    assert decision.route_decision is not None
    assert decision.route_decision.needs_clarification is True


def test_decision_engine_public_workflow_no_longer_depends_on_internal_workflow() -> None:
    understanding = UnderstandingResult(
        normalized_text="what is your return policy",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="catalog_search",
        intent_confidence=0.9,
        reason="policy_signal_detected",
        entity_hints={
            "has_policy_signal": True,
            "has_knowledge_signal": True,
            "preferred_knowledge_query": "what is your return policy",
        },
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="what is your return policy",
        channel="widget",
    )

    assert decision.internal_workflow == "catalog_search"
    assert decision.public_workflow == "catalog"
    assert decision.route_decision is not None
    assert decision.route_decision.workflow == "catalog"
    assert decision.route_decision.knowledge_query == ""


def test_decision_engine_execution_mode_no_longer_depends_on_legacy_workflow_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")

    understanding = UnderstandingResult(
        normalized_text="show me titanium labrets",
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis="off_topic",
        intent_confidence=0.91,
        reason="catalog_signal_detected",
        needs_products=True,
        entity_hints={
            "has_product_signal": True,
            "has_product_search_signal": True,
        },
    )

    decision = build_decision_state(
        understanding=understanding,
        user_text="show me titanium labrets",
        channel="widget",
    )

    assert decision.public_workflow == "off_topic"
    assert decision.execution_decision is not None
    assert decision.execution_decision.execution_mode == "component"
    assert decision.execution_decision.tool_suitable is False


def test_classify_fallback_reason_is_shared_between_routing_and_knowledge_paths() -> None:
    route_reason = classify_fallback_reason(
        text="help me",
        route_reason="",
        blank_reason="fallback_missing_signal",
        default_reason="fallback_vague_store_request",
    )
    knowledge_reason = classify_fallback_reason(
        text="help me",
        route_reason="",
        blank_reason="fallback_gibberish",
        default_reason="fallback_missing_signal",
        vague_hints=("help", "assist", "can you help", "need help"),
    )

    assert route_reason == "fallback_vague_store_request"
    assert knowledge_reason == "fallback_vague_store_request"
