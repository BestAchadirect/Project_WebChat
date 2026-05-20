from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.services.chat.agentic.orchestrator import AgentRunResult
from app.services.chat.parsing.llm_attribute_extractor import DetailQueryInferenceResult
from app.services.chat.routing.contracts import UnderstandingResult
from app.services.chat.service import ChatService
from tests.fixtures.chat import build_component_pipeline_result, patch_chat_service_lifecycle


def _understanding_result(
    *,
    text: str,
    workflow: str,
    intent: str,
    reason: str,
    confidence: float = 0.9,
    needs_products: bool = False,
    needs_knowledge: bool = False,
    knowledge_query: str = "",
    sku_tokens: list[str] | None = None,
    entity_hints: dict | None = None,
) -> UnderstandingResult:
    return UnderstandingResult(
        normalized_text=text,
        locale="en-US",
        channel="widget",
        sku_tokens=list(sku_tokens or []),
        workflow_hypothesis=workflow,
        intent_confidence=confidence,
        reason=reason,
        knowledge_query=knowledge_query,
        needs_products=needs_products,
        needs_knowledge=needs_knowledge,
        intent=intent,
        response_policy="answer_from_retrieved_data"
        if needs_products or needs_knowledge
        else "ask_clarifying_question",
        entity_hints=dict(entity_hints or {}),
        llm_call_count=1,
        debug={"understanding_source": "test"},
    )


def _patch_runtime_understanding(monkeypatch: pytest.MonkeyPatch, result: UnderstandingResult) -> None:
    async def fake_understanding(**kwargs):
        return result

    monkeypatch.setattr("app.services.chat.harness.dependencies.build_understanding_result", fake_understanding)


@pytest.mark.asyncio
async def test_harness_trace_created_for_simple_component_request(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="component response",
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")
    _patch_runtime_understanding(
        monkeypatch,
        _understanding_result(
            text="list steel rings",
            workflow="catalog_search",
            intent="product_information",
            reason="catalog request",
            needs_products=True,
        ),
    )
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    response = await ChatService(db=object()).process_chat(
        ChatRequest(user_id="guest-trace-1", message="list steel rings", locale="en-US"),
        channel="widget",
    )

    trace = response.debug.get("harness_trace")
    assert isinstance(trace, dict)
    assert str(trace.get("run_id") or "").startswith("chat-")
    assert trace.get("route") == "catalog"
    assert trace.get("execution_mode") == "component"
    assert response.debug["agentic"]["route_supported"] is True
    assert response.debug["agentic"]["tool_first_candidate"] is True
    assert response.debug["agentic"]["selection_blockers"] == ["feature_disabled"]
    assert trace["metadata"]["agentic_selection"]["selection_blockers"] == ["feature_disabled"]
    assert "workflow" in response.debug
    assert response.debug.get("component_mode") == "primary"


@pytest.mark.asyncio
async def test_harness_trace_records_catalog_product_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="I found a matching ring.",
            product_carousel=[
                {
                    "sku": "RING-1",
                    "name": "Steel Ring",
                    "price": 12.0,
                    "currency": "USD",
                    "stock_status": "in_stock",
                    "attributes": {"material": "Steel"},
                }
            ],
            debug={"grounding_status": "grounded", "grounding_safe_action": "answer"},
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    _patch_runtime_understanding(
        monkeypatch,
        _understanding_result(
            text="show steel rings",
            workflow="catalog_search",
            intent="product_information",
            reason="catalog request",
            needs_products=True,
            entity_hints={"has_product_signal": True},
        ),
    )
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    response = await ChatService(db=object()).process_chat(
        ChatRequest(user_id="guest-trace-2", message="show steel rings", locale="en-US"),
        channel="widget",
    )

    trace = response.debug["harness_trace"]
    assert trace["route"] == "catalog"
    assert trace["workflow"] == "catalog_search"
    assert trace["retrieved_products"] >= 1
    assert trace["grounding_status"] == "grounded"
    assert trace["fallback_used"] is False
    assert {"prepare_context", "understand", "route", "execute", "finalize"}.issubset(trace["timings_ms"])


@pytest.mark.asyncio
async def test_harness_understanding_wrapper_preserves_detail_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_infer_detail_query(**kwargs):
        return DetailQueryInferenceResult(
            requested_fields=["price"],
            attribute_filters={},
            wants_image=False,
            semantic_hints=[],
            unknown_terms=[],
            clarify_focus="",
            confidence=0.95,
            llm_call_count=2,
            debug={"llm_detail_query_test": True},
        )

    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        detail = kwargs.get("detail_override")
        assert list(getattr(detail, "requested_fields", []) or []) == ["price"]
        assert kwargs.get("llm_call_count_override") == 3
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="The item price is available on the product card.",
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    _patch_runtime_understanding(
        monkeypatch,
        _understanding_result(
            text="what is the price for ABC-1",
            workflow="product_detail",
            intent="product_information",
            reason="product detail request",
            needs_products=True,
            sku_tokens=["ABC-1"],
            entity_hints={"has_product_signal": True, "has_product_detail_signal": True},
        ),
    )
    monkeypatch.setattr("app.services.chat.harness.dependencies.infer_detail_query", fake_infer_detail_query)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    response = await ChatService(db=object()).process_chat(
        ChatRequest(user_id="guest-trace-detail", message="what is the price for ABC-1", locale="en-US"),
        channel="widget",
    )

    assert response.debug["llm_detail_query_test"] is True
    assert response.debug["harness_trace"]["workflow"] == "product_detail"
    assert "understand" in response.debug["harness_trace"]["timings_ms"]


@pytest.mark.asyncio
async def test_harness_trace_records_knowledge_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="Our return policy is 30 days.",
            response_workflow="knowledge",
            source="knowledge",
            sources=[
                {
                    "source_id": "kb-return",
                    "title": "Return Policy",
                    "content_snippet": "Returns are accepted within 30 days.",
                    "category": "Policy",
                    "relevance": 0.95,
                }
            ],
            debug={"knowledge_grounding_status": "grounded", "knowledge_grounding_safe_action": "answer"},
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    _patch_runtime_understanding(
        monkeypatch,
        _understanding_result(
            text="what is your return policy?",
            workflow="policy_info",
            intent="knowledge_policy",
            reason="policy request",
            needs_knowledge=True,
            knowledge_query="what is your return policy?",
            entity_hints={"has_knowledge_signal": True},
        ),
    )
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    response = await ChatService(db=object()).process_chat(
        ChatRequest(user_id="guest-trace-3", message="what is your return policy?", locale="en-US"),
        channel="widget",
    )

    trace = response.debug["harness_trace"]
    assert trace["route"] == "knowledge"
    assert trace["workflow"] == "policy_info"
    assert trace["retrieved_sources"] >= 1
    assert trace["grounding_status"] == "grounded"


@pytest.mark.asyncio
async def test_harness_routing_wrapper_preserves_fallback_route(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        route_override = kwargs.get("route_decision_override")
        assert str(getattr(route_override, "workflow", "")) == "fallback"
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="Could you share a little more detail?",
            response_workflow="fallback",
            source="error",
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    _patch_runtime_understanding(
        monkeypatch,
        _understanding_result(
            text="help",
            workflow="clarify",
            intent="clarify",
            reason="fallback_missing_signal",
            confidence=0.4,
        ),
    )
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    response = await ChatService(db=object()).process_chat(
        ChatRequest(user_id="guest-trace-fallback", message="help", locale="en-US"),
        channel="widget",
    )

    trace = response.debug["harness_trace"]
    assert response.debug["workflow"] == "fallback"
    assert trace["route"] == "fallback"
    assert trace["fallback_used"] is True
    assert "route" in trace["timings_ms"]


@pytest.mark.asyncio
async def test_harness_trace_records_agentic_fallback_and_tool_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_agentic_workflow(
        self,
        *,
        user_text: str,
        conversation_id: int,
        run_id: str,
        channel: str,
        reply_language: str,
    ):
        return AgentRunResult.empty(
            trace=[
                {
                    "tool": "check_inventory_db",
                    "status": "error",
                    "tool_status": "empty",
                    "duration_ms": 7,
                    "result_count": 0,
                }
            ]
        )

    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="component fallback response",
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    _patch_runtime_understanding(
        monkeypatch,
        _understanding_result(
            text="stock for ABC-1",
            workflow="product_detail",
            intent="product_information",
            reason="stock lookup",
            needs_products=True,
            sku_tokens=["ABC-1"],
            entity_hints={"has_product_signal": True, "has_product_detail_signal": True},
        ),
    )
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")
    monkeypatch.setattr(settings, "AGENTIC_ENABLE_FALLBACK", True)
    monkeypatch.setattr(ChatService, "_run_agentic_workflow", fake_agentic_workflow)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    response = await ChatService(db=object()).process_chat(
        ChatRequest(user_id="guest-trace-4", message="stock for ABC-1", locale="en-US"),
        channel="widget",
    )

    trace = response.debug["harness_trace"]
    assert trace["fallback_used"] is True
    assert trace["fallback_reason"] == "empty_result"
    assert "check_inventory_db" in trace["tools_called"]
    assert trace["metadata"]["tool_events"][0]["result_count"] == 0
    assert (response.debug.get("agentic") or {}).get("fallback_to_component") is True


@pytest.mark.asyncio
async def test_harness_trace_preserves_component_first_response_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="component contract response",
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    _patch_runtime_understanding(
        monkeypatch,
        _understanding_result(
            text="list titanium labrets",
            workflow="catalog_search",
            intent="product_information",
            reason="catalog request",
            needs_products=True,
        ),
    )
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    response = await ChatService(db=object()).process_chat(
        ChatRequest(user_id="guest-trace-5", message="list titanium labrets", locale="en-US"),
        channel="widget",
    )

    payload = response.model_dump(mode="json")
    assert "reply_text" not in payload
    assert "product_carousel" not in payload
    assert "follow_up_questions" not in payload
    assert payload["components"][0]["type"] == "assistant_message"
    assert "harness_trace" in payload["debug"]
    assert payload["debug"]["workflow"] == "catalog"
    assert payload["debug"]["component_mode"] == "primary"
