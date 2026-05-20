from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatRequest, ChatRouting
from app.services.ai.llm_service import llm_service
from app.services.chat.agentic.orchestrator import AgentRunResult
from app.services.chat.harness.context import ChatHarnessContext
from app.services.chat.harness.executor import HarnessExecutionResult
from app.services.chat.harness.finalizer import run_error_finalization, run_finalization
from app.services.chat.harness.router import HarnessRouteResult
from app.services.chat.harness.trace import HarnessTrace
from app.services.chat.service import ChatService
from tests.fixtures.chat import build_component_pipeline_result, build_product_cards


class RollbackDB:
    def __init__(self) -> None:
        self.rolled_back = False

    async def rollback(self) -> None:
        self.rolled_back = True


def _patch_finalize_io(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_finalize_response(self, **kwargs: Any):
        self.finalize_calls = list(getattr(self, "finalize_calls", [])) + [dict(kwargs)]
        return kwargs["response"]

    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(ChatService, "_log_event", lambda self, **kwargs: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {"prompt_tokens": 1})


def _context(
    *,
    service: ChatService,
    message: str = "show steel rings",
    conversation_id: int = 42,
    debug_meta: dict[str, Any] | None = None,
) -> ChatHarnessContext:
    run_id = "chat-finalizer-test"
    request = ChatRequest(
        user_id="finalizer-user",
        message=message,
        locale="en-US",
        conversation_id=conversation_id,
    )
    return ChatHarnessContext(
        service=service,
        request=request,
        channel="widget",
        trace=HarnessTrace(
            run_id=run_id,
            conversation_id=str(conversation_id),
            user_id=request.user_id,
            user_message=request.message,
        ),
        run_id=run_id,
        user_text=request.message,
        conversation_id_value=conversation_id,
        total_started=time.perf_counter(),
        spans=service._new_latency_spans(),
        capabilities=SimpleNamespace(),
        debug_meta={
            "run_id": run_id,
            "workflow": "catalog",
            "execution_mode": "component",
            **dict(debug_meta or {}),
        },
        current_step="finalize",
        step_started=time.perf_counter(),
    )


def _route_result(*, workflow: str = "catalog", execution_mode: str = "component") -> HarnessRouteResult:
    public_routing = ChatRouting(
        workflow=workflow,
        execution_mode=execution_mode,
        needs_products=workflow == "catalog",
        needs_knowledge=workflow == "knowledge",
        needs_clarification=workflow == "fallback",
        reason="fixture",
        selection_source="fixture",
    )
    return HarnessRouteResult(
        decision_state=SimpleNamespace(internal_workflow=f"{workflow}_internal"),
        route_decision=SimpleNamespace(workflow=workflow),
        execution_decision=SimpleNamespace(execution_mode=execution_mode),
        public_routing=public_routing,
        selection_source="fixture",
        execution_mode=execution_mode,
    )


@pytest.mark.asyncio
async def test_finalizer_component_path_preserves_latency_persistence_and_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_finalize_io(monkeypatch)
    service = ChatService(db=object())
    context = _context(service=service)
    component_result = build_component_pipeline_result(
        request=context.request,
        conversation_id=context.conversation_id_value,
        reply_text="I found a steel ring.",
        product_carousel=[
            {
                "sku": "RING-1",
                "name": "Steel Ring",
                "price": 12.0,
                "currency": "USD",
            }
        ],
        debug={"grounding_status": "grounded"},
        conversation_state={"last_workflow": "catalog"},
    )

    result = await run_finalization(
        context=context,
        route_result=_route_result(),
        execution_result=HarnessExecutionResult(path="component", component_result=component_result),
    )

    response = result.response
    trace = response.debug["harness_trace"]
    assert response.debug["component_mode"] == "primary"
    assert "latency_spans" in response.debug
    assert trace["route"] == "catalog"
    assert trace["grounding_status"] == "grounded"
    assert trace["retrieved_products"] == 1
    assert "finalize" in trace["timings_ms"]
    assert service.finalize_calls[0]["conversation_state"] == {"last_workflow": "catalog"}


@pytest.mark.asyncio
async def test_finalizer_agentic_path_builds_tool_response_and_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_finalize_io(monkeypatch)
    service = ChatService(db=object())
    context = _context(
        service=service,
        message="stock for RING-1",
        debug_meta={
            "execution_mode": "agentic",
            "agentic": {
                "trace": [
                    {
                        "tool": "check_inventory_db",
                        "status": "ok",
                        "duration_ms": 5,
                        "result_count": 1,
                    }
                ],
                "fallback_to_component": False,
            },
        },
    )
    agentic_result = AgentRunResult.tool_success(
        final_reply="RING-1 is in stock.",
        product_carousel=build_product_cards(
            [{"sku": "RING-1", "name": "Steel Ring", "price": 12.0, "currency": "USD"}]
        ),
        trace=[{"tool": "check_inventory_db", "status": "ok", "duration_ms": 5, "result_count": 1}],
    )

    result = await run_finalization(
        context=context,
        route_result=_route_result(execution_mode="agentic"),
        execution_result=HarnessExecutionResult(path="agentic", agentic_result=agentic_result),
    )

    response = result.response
    trace = response.debug["harness_trace"]
    assert response.meta.source == "tool"
    assert response.routing.execution_mode == "agentic"
    assert response.product_carousel[0].sku == "RING-1"
    assert "check_inventory_db" in trace["tools_called"]
    assert trace["metadata"]["tool_events"][0]["result_count"] == 1
    assert "finalize" in trace["timings_ms"]


@pytest.mark.asyncio
async def test_finalizer_runtime_error_rolls_back_and_records_fallback_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_finalize_io(monkeypatch)
    db = RollbackDB()
    service = ChatService(db=db)
    context = _context(service=service)

    result = await run_error_finalization(
        context=context,
        error=RuntimeError("boom"),
    )

    response = result.response
    trace = response.debug["harness_trace"]
    assert db.rolled_back is True
    assert response.routing.workflow == "fallback"
    assert response.debug["component_mode"] == "error"
    assert response.debug["component_pipeline_error"] == "boom"
    assert "latency_spans" in response.debug
    assert trace["fallback_used"] is True
    assert trace["fallback_reason"]
    assert "boom" in trace["errors"]
    assert "finalize" in trace["timings_ms"]
