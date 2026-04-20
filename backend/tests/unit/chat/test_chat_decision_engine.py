from __future__ import annotations

from app.core.config import settings
from app.prompts.routing import understanding_workflow_prompt
from app.services.chat.routing.decision_engine import build_decision_state
from app.services.chat.routing.contracts import UnderstandingResult
from app.services.chat.routing.understanding import build_understanding_result


async def _understanding(text: str):
    return await build_understanding_result(
        user_text=text,
        locale="en-US",
        channel="widget",
    )


import pytest


@pytest.mark.asyncio
async def test_decision_engine_projects_company_info_to_public_knowledge() -> None:
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
async def test_decision_engine_projects_mixed_to_public_catalog_with_knowledge() -> None:
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


@pytest.mark.asyncio
async def test_decision_engine_prefers_agentic_for_supported_catalog_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")

    understanding = await _understanding("show me titanium labrets")
    decision = build_decision_state(
        understanding=understanding,
        user_text="show me titanium labrets",
        channel="widget",
    )

    assert decision.public_workflow == "catalog"
    assert decision.execution_decision is not None
    assert decision.execution_decision.execution_mode == "agentic"
    assert decision.execution_decision.selection_source == "staged_agentic"
    assert decision.execution_decision.tool_suitable is True


@pytest.mark.asyncio
async def test_decision_engine_prefers_agentic_for_supported_knowledge_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")

    understanding = await _understanding("What is your shipping policy?")
    decision = build_decision_state(
        understanding=understanding,
        user_text="What is your shipping policy?",
        channel="widget",
    )

    assert decision.public_workflow == "knowledge"
    assert decision.execution_decision is not None
    assert decision.execution_decision.execution_mode == "agentic"
    assert decision.execution_decision.selection_source == "staged_agentic"
    assert decision.execution_decision.tool_suitable is True


def test_understanding_prompt_uses_internal_workflow_taxonomy() -> None:
    prompt = understanding_workflow_prompt()

    assert "catalog_search" in prompt
    assert "company_info" in prompt
    assert "policy_info" in prompt
    assert "fallback" not in prompt
