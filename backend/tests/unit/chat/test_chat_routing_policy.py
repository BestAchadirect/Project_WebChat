import asyncio
from typing import Any

import pytest

from app.core.config import settings
from app.services.ai.llm_service import llm_service
from app.services.chat.routing import routing_policy


def test_extract_sku_tokens_dedupes_and_filters_noise() -> None:
    tokens = routing_policy.extract_sku_tokens("check ABC-1 and abc-1, then SKU_XY-22 and hello-world")
    assert tokens == ["ABC-1", "SKU_XY-22"]


def test_agentic_tool_suitability_allows_supported_read_only_requests() -> None:
    assert (
        routing_policy.is_agentic_tool_suitable(
            user_text="What is your shipping policy?",
            workflow="knowledge",
            sku_token=None,
            needs_products=False,
            needs_knowledge=True,
        )
        is True
    )
    assert (
        routing_policy.is_agentic_tool_suitable(
            user_text="Show me titanium labrets",
            workflow="catalog",
            sku_token=None,
            needs_products=True,
            needs_knowledge=False,
        )
        is True
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
    assert (
        routing_policy.is_agentic_tool_suitable(
            user_text="hello there",
            workflow="off_topic",
            sku_token=None,
            needs_products=False,
            needs_knowledge=False,
        )
        is False
    )
    assert (
        routing_policy.is_agentic_tool_suitable(
            user_text="find something nice",
            workflow="catalog",
            sku_token=None,
            needs_products=False,
            needs_knowledge=False,
        )
        is False
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
    assert decision.route_decision.knowledge_query == ""


@pytest.mark.asyncio
async def test_llm_routing_returns_off_topic_workflow_for_casual_greeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "off_topic",
            "execution_mode": "component",
            "needs_products": False,
            "needs_knowledge": False,
            "needs_clarification": False,
            "store_overview_request": False,
            "reason": "casual store greeting",
            "confidence": 0.91,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Hi there",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "off_topic"
    assert decision.route_decision.needs_products is False
    assert decision.route_decision.needs_knowledge is False
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm"
    assert decision.llm_workflow == "off_topic"


@pytest.mark.asyncio
async def test_llm_routing_keeps_casual_fallback_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "fallback",
            "execution_mode": "component",
            "needs_products": False,
            "needs_knowledge": False,
            "needs_clarification": True,
            "store_overview_request": False,
            "reason": "hi there",
            "confidence": 0.61,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Hi there",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "fallback"
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm_fallback"
    assert decision.confidence_gate_applied is True
    assert decision.route_decision.needs_clarification is True
    assert decision.llm_workflow == "fallback"


@pytest.mark.asyncio
async def test_llm_routing_returns_off_topic_workflow_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "off_topic",
            "execution_mode": "component",
            "needs_products": False,
            "needs_knowledge": False,
            "needs_clarification": False,
            "store_overview_request": False,
            "reason": "unrelated non-store request",
            "confidence": 0.94,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Can you write Python code for me?",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "off_topic"
    assert decision.route_decision.needs_products is False
    assert decision.route_decision.needs_knowledge is False
    assert decision.route_decision.needs_clarification is False
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm"
    assert decision.llm_workflow == "off_topic"
    assert decision.route_decision.knowledge_query == ""


@pytest.mark.asyncio
async def test_llm_routing_soft_accepts_medium_confidence_catalog_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "catalog",
            "execution_mode": "component",
            "needs_products": True,
            "needs_knowledge": False,
            "needs_clarification": False,
            "store_overview_request": False,
            "reason": "broad shopping request for something elegant",
            "confidence": 0.62,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="show me something elegant",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "catalog"
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm_soft"
    assert decision.confidence_gate_applied is True
    assert decision.llm_workflow == "catalog"


@pytest.mark.asyncio
async def test_llm_routing_soft_accepts_medium_confidence_knowledge_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "knowledge",
            "execution_mode": "component",
            "needs_products": False,
            "needs_knowledge": True,
            "needs_clarification": False,
            "store_overview_request": False,
            "reason": "store policy question",
            "confidence": 0.63,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="what is your shipping policy?",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "knowledge"
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm_soft"
    assert decision.confidence_gate_applied is True
    assert decision.llm_workflow == "knowledge"


@pytest.mark.asyncio
async def test_llm_routing_keeps_directional_fallback_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "fallback",
            "execution_mode": "component",
            "needs_products": True,
            "needs_knowledge": False,
            "needs_clarification": True,
            "store_overview_request": False,
            "reason": "broad shopping request for titanium jewelry",
            "confidence": 0.61,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="show me something in titanium",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "fallback"
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm_fallback"
    assert decision.confidence_gate_applied is True
    assert decision.route_decision.needs_clarification is True
    assert decision.reason == "confidence_below_threshold"
    assert decision.llm_workflow == "fallback"


@pytest.mark.asyncio
async def test_llm_routing_invalid_payload_falls_back_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        return ["not", "a", "dict"]

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Can you help me?",
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
    assert decision.llm_reason == "invalid_payload"


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
        text="asdfafafdas",
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
async def test_llm_routing_timeout_uses_catalog_guardrail_for_product_like_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Do you have sterilization with opal?",
        channel="widget",
        locale="en-US",
        detail_has_filters=True,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "catalog"
    assert decision.route_decision.needs_products is True
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm_timeout_guardrail"
    assert decision.reason == "routing_timeout_guardrail"
    assert decision.llm_reason == "error:TimeoutError"


@pytest.mark.asyncio
async def test_llm_routing_timeout_falls_back_for_knowledge_message_without_structural_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="How can I contact your sales team?",
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
    assert decision.reason == "routing_error"
    assert decision.llm_reason == "error:TimeoutError"


@pytest.mark.asyncio
async def test_llm_routing_timeout_retries_with_compact_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {"count": 0, "system_prompts": []}

    async def fake_generate_chat_json(**kwargs):
        calls["count"] += 1
        messages = list(kwargs.get("messages") or [])
        calls["system_prompts"].append(str(messages[0]["content"] if messages else ""))
        if calls["count"] == 1:
            raise asyncio.TimeoutError()
        return {
            "workflow": "knowledge",
            "execution_mode": "component",
            "needs_products": False,
            "needs_knowledge": True,
            "needs_clarification": False,
            "store_overview_request": True,
            "reason": "contact request",
            "confidence": 0.92,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_TIMEOUT_RETRY_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_TIMEOUT_RETRY_MS", 1800)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="How can I contact your sales team?",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert calls["count"] == 2
    assert len(calls["system_prompts"][1]) < len(calls["system_prompts"][0])
    assert "knowledge_query" in calls["system_prompts"][0]
    assert "knowledge_query" in calls["system_prompts"][1]
    assert decision.route_decision.workflow == "knowledge"
    assert decision.execution_mode == "component"
    assert decision.selection_source == "llm_retry"
    assert decision.timeout_retry_used is True


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
async def test_llm_routing_prompt_includes_expected_schema_and_workflow_examples(
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
    assert "Return ONLY strict JSON" in system_prompt
    assert "knowledge_query" in system_prompt
    assert "off_topic" in system_prompt
    assert "I want to talk to a sales person" in system_prompt
    assert "How do I contact support?" in system_prompt
    assert "support/contact requests" in system_prompt
    assert "set needs_knowledge=true" in system_prompt
    assert "User:" not in system_prompt


@pytest.mark.asyncio
async def test_llm_routing_keeps_location_knowledge_query_for_mixed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "catalog",
            "execution_mode": "component",
            "needs_products": True,
            "needs_knowledge": True,
            "needs_clarification": False,
            "store_overview_request": False,
            "knowledge_query": "when is your Thailand showroom open next week",
            "reason": "mixed request with store-hours follow-up",
            "confidence": 0.93,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="I want to buy barbell product and also next week i'm going to thailand when are your store going to open?",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "catalog"
    assert decision.route_decision.needs_knowledge is True
    assert decision.route_decision.knowledge_query == "when is your Thailand showroom open next week"


@pytest.mark.asyncio
async def test_llm_routing_keeps_payment_knowledge_query_for_mixed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(**kwargs):
        return {
            "workflow": "catalog",
            "execution_mode": "component",
            "needs_products": True,
            "needs_knowledge": True,
            "needs_clarification": False,
            "store_overview_request": False,
            "knowledge_query": "what payment methods do you accept",
            "reason": "mixed request with payment follow-up",
            "confidence": 0.93,
        }

    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    decision = await routing_policy.decide_execution_mode_with_llm(
        text="Show me titanium jewelry and also what payment methods do you accept?",
        channel="widget",
        locale="en-US",
        detail_has_filters=False,
        detail_request=False,
        sku_tokens=[],
    )

    assert decision.route_decision.workflow == "catalog"
    assert decision.route_decision.needs_knowledge is True
    assert decision.route_decision.knowledge_query == "what payment methods do you accept"
