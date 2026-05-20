from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.services.chat.agentic.orchestrator import AgentRunOutcome, AgentRunResult
from app.services.chat.harness.context import ChatHarnessContext
from app.services.chat.harness.executor import run_execution
from app.services.chat.harness.router import HarnessRouteResult
from app.services.chat.harness.trace import HarnessTrace
from app.services.chat.harness.understanding import HarnessUnderstandingResult
from app.services.chat.runtime.agentic_adapter import (
    apply_agentic_fallback_debug,
    apply_agentic_success_debug,
    coerce_agentic_result,
)
from app.services.chat.runtime.fallback_policy import agentic_failure_reason


class RollbackTrackingDB:
    def __init__(self) -> None:
        self.rollback_calls = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1


class FallbackService:
    def __init__(self) -> None:
        self.db = RollbackTrackingDB()
        self.component_called_after_rollback = False

    async def _run_agentic_workflow(self, **kwargs):
        del kwargs
        return AgentRunResult.empty(
            trace=[
                {
                    "tool": "search_products",
                    "status": "timeout",
                    "result_count": 0,
                }
            ]
        )

    async def _run_component_pipeline(self, **kwargs):
        del kwargs
        self.component_called_after_rollback = self.db.rollback_calls == 1
        return SimpleNamespace(
            response=SimpleNamespace(),
            debug={},
            external_call_counts={},
            llm_calls=0,
            spans={},
        )

    def _add_latency_span(self, spans, key, elapsed_ms):
        spans[key] = elapsed_ms


class SearchPlanStub:
    def expected_tool_groups(self):
        return [["search_products"]]

    def expected_tools(self):
        return ["search_products"]


@pytest.mark.asyncio
async def test_agentic_empty_fallback_rolls_back_before_component_pipeline() -> None:
    service = FallbackService()
    context = ChatHarnessContext(
        service=service,
        request=SimpleNamespace(message="opal sterilization", locale="en-US"),
        channel="widget",
        trace=HarnessTrace(run_id="test-run"),
        run_id="test-run",
        user_text="opal sterilization",
        conversation_id_value=123,
        total_started=time.perf_counter(),
        spans={},
        capabilities=SimpleNamespace(agentic_enable_fallback=True),
        debug_meta={},
        step_started=time.perf_counter(),
    )
    dependencies = SimpleNamespace(
        build_search_plan=lambda **kwargs: SearchPlanStub(),
        coerce_agentic_result=coerce_agentic_result,
        apply_agentic_fallback_debug=apply_agentic_fallback_debug,
        apply_agentic_success_debug=apply_agentic_success_debug,
        AgentRunOutcome=AgentRunOutcome,
        agentic_failure_reason=agentic_failure_reason,
    )
    understanding_result = HarnessUnderstandingResult(
        user=SimpleNamespace(),
        conversation=SimpleNamespace(id=123),
        understanding=SimpleNamespace(llm_call_count=0),
        detail=None,
        detail_llm_calls=0,
        sku_tokens=[],
        alias_map={},
        parser_rules=[],
        existing_attribute_filters={},
        searchable_attribute_names=[],
        searchable_attribute_metadata=[],
    )
    route_result = HarnessRouteResult(
        decision_state=SimpleNamespace(internal_workflow="catalog_search"),
        route_decision=SimpleNamespace(workflow="catalog", knowledge_query=""),
        execution_decision=SimpleNamespace(),
        public_routing=SimpleNamespace(),
        selection_source="policy",
        execution_mode="agentic",
    )

    result = await run_execution(
        context=context,
        dependencies=dependencies,
        understanding_result=understanding_result,
        route_result=route_result,
    )

    assert result.path == "component"
    assert service.db.rollback_calls == 1
    assert service.component_called_after_rollback is True
    assert context.debug_meta["agentic_component_fallback_rollback"] is True
    assert context.debug_meta["agentic_component_fallback_rollback_reason"] == "empty_result"
