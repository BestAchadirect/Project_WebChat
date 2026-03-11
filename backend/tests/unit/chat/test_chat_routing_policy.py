import asyncio

import pytest

from app.core.config import settings
from app.services.ai.llm_service import llm_service
from app.services.chat import routing_policy


def test_extract_sku_tokens_dedupes_and_filters_noise() -> None:
    tokens = routing_policy.extract_sku_tokens("check ABC-1 and abc-1, then SKU_XY-22 and hello-world")
    assert tokens == ["ABC-1", "SKU_XY-22"]


def test_agentic_tool_suitability_requires_supported_workflow() -> None:
    assert (
        routing_policy.is_agentic_tool_suitable(
            user_text="What is your shipping policy?",
            workflow="knowledge",
            sku_token=None,
            needs_products=False,
            needs_knowledge=True,
        )
        is False
    )
    assert (
        routing_policy.is_agentic_tool_suitable(
            user_text="Check stock for ABC-1",
            workflow="catalog",
            sku_token="ABC-1",
            needs_products=True,
            needs_knowledge=False,
        )
        is True
    )


@pytest.mark.asyncio
async def test_llm_routing_returns_catalog_workflow_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "catalog",
            "execution_mode": "component",
            "needs_products": True,
            "needs_knowledge": False,
            "needs_clarification": False,
            "store_overview_request": False,
            "reason": "browse request",
            "confidence": 0.91,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_SHADOW_MODE", False)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Show me titanium labrets",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "catalog"
    assert decision.route_decision.needs_products is True
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm"
    assert decision.llm_workflow == "catalog"


@pytest.mark.asyncio
async def test_llm_routing_confidence_gate_forces_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "knowledge",
            "execution_mode": "component",
            "needs_products": False,
            "needs_knowledge": True,
            "needs_clarification": False,
            "store_overview_request": False,
            "reason": "uncertain",
            "confidence": 0.42,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Can I have your contact details?",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "fallback"
    assert decision.route_decision.needs_clarification is True
    assert decision.execution_mode == "component"
    assert decision.reason == "confidence_below_threshold"
    assert decision.selection_source == "llm_fallback"
    assert decision.confidence_gate_applied is True
    assert decision.llm_workflow == "knowledge"


@pytest.mark.asyncio
async def test_llm_routing_agentic_guardrails_require_feature_channel_and_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "catalog",
            "execution_mode": "agentic",
            "needs_products": True,
            "needs_knowledge": False,
            "needs_clarification": False,
            "store_overview_request": False,
            "reason": "stock check",
            "confidence": 0.95,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(settings, "CHAT_AGENTIC_MIN_CONFIDENCE", 0.8)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Check stock for ABC-1",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=["ABC-1"],
    )

    assert decision.route_decision.workflow == "catalog"
    assert decision.execution_mode == "component"
    assert decision.reason == "feature_disabled"
    assert decision.selection_source == "llm_guardrail"
    assert decision.tool_suitable is True


@pytest.mark.asyncio
async def test_llm_routing_timeout_falls_back_to_safe_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_generate_chat_json(**kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Show me something",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "fallback"
    assert decision.route_decision.needs_clarification is True
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm_fallback"
    assert decision.llm_reason == "error:TimeoutError"


@pytest.mark.asyncio
async def test_llm_routing_prefers_nlu_model_when_routing_model_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def fake_generate_chat_json(**kwargs):
        captured["model"] = str(kwargs.get("model") or "")
        captured["reasoning_effort"] = str(kwargs.get("reasoning_effort") or "")
        return {
            "workflow": "knowledge",
            "execution_mode": "component",
            "needs_products": False,
            "needs_knowledge": True,
            "needs_clarification": False,
            "store_overview_request": False,
            "reason": "knowledge request",
            "confidence": 0.93,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MODEL", "")
    monkeypatch.setattr(settings, "NLU_MODEL", "gpt-5-mini")
    monkeypatch.setattr(settings, "OPENAI_MODEL", "gpt-5.4")
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Where is your company?",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert captured["model"] == "gpt-5-mini"
    assert captured["reasoning_effort"] == "minimal"
    assert decision.route_decision.workflow == "knowledge"
    assert decision.selection_source == "llm"


@pytest.mark.asyncio
async def test_llm_routing_prompt_includes_company_and_recommendation_examples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def fake_generate_chat_json(**kwargs):
        messages = list(kwargs.get("messages") or [])
        captured["system"] = str(messages[0]["content"] if messages else "")
        return {
            "workflow": "knowledge",
            "execution_mode": "component",
            "needs_products": False,
            "needs_knowledge": True,
            "needs_clarification": False,
            "store_overview_request": True,
            "reason": "knowledge request",
            "confidence": 0.93,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    await routing_policy.decide_execution_mode_with_llm(
        text="test prompt",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    system_prompt = captured["system"]
    assert 'User: "what is your company?"' in system_prompt
    assert 'User: "Do you have any product suggest?"' in system_prompt
