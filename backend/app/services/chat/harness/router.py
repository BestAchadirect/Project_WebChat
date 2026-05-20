from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.services.chat.harness.context import ChatHarnessContext, ChatHarnessDependencies
from app.services.chat.harness.understanding import HarnessUnderstandingResult


@dataclass(frozen=True)
class HarnessRouteResult:
    decision_state: Any
    route_decision: Any
    execution_decision: Any
    public_routing: Any
    selection_source: str
    execution_mode: str


async def run_routing(
    *,
    context: ChatHarnessContext,
    dependencies: ChatHarnessDependencies,
    understanding_result: HarnessUnderstandingResult,
) -> HarnessRouteResult:
    context.current_step = "route"
    context.step_started = time.perf_counter()

    understanding = understanding_result.understanding
    debug_meta = context.debug_meta
    decision_state = dependencies.build_decision_state(
        understanding=understanding,
        user_text=context.user_text,
        channel=context.channel,
        capabilities=context.capabilities,
    )
    debug_meta["decision_state"] = {
        "internal_workflow": decision_state.internal_workflow,
        "public_workflow": decision_state.public_workflow,
        "intent_confidence": decision_state.intent_confidence,
        "retrieval_confidence": decision_state.retrieval_confidence,
        "answerability": decision_state.answerability,
        "reason": decision_state.reason,
        "failure_reason": decision_state.failure_reason,
        "intent": decision_state.intent,
        "subintent": decision_state.subintent,
        "response_policy": decision_state.response_policy,
        "user_goal": decision_state.user_goal,
    }

    execution_decision = decision_state.execution_decision
    if execution_decision is None or decision_state.route_decision is None:
        raise RuntimeError("decision engine returned no route decision")
    route_decision = execution_decision.route_decision
    selection_source = execution_decision.selection_source
    execution_mode = execution_decision.execution_mode
    public_routing = route_decision.to_public_routing(
        execution_mode=execution_mode,
        selection_source=selection_source,
    )

    debug_meta["workflow"] = route_decision.workflow
    debug_meta["workflow_source"] = route_decision.source.value
    debug_meta["workflow_needs_products"] = route_decision.needs_products
    debug_meta["workflow_needs_knowledge"] = route_decision.needs_knowledge
    debug_meta["workflow_needs_clarification"] = route_decision.needs_clarification
    debug_meta["workflow_store_overview_request"] = route_decision.store_overview_request
    debug_meta["execution_mode"] = execution_mode
    debug_meta["routing_selection_source"] = selection_source
    debug_meta["routing"] = public_routing.model_dump(mode="json")
    debug_meta["routing_snapshot"] = dependencies.runtime_metrics.routing_snapshot(
        route_decision=route_decision,
        execution_decision=execution_decision,
    )
    debug_meta["routing_confidence_gate_applied"] = execution_decision.confidence_gate_applied
    debug_meta["routing_timeout_retry_used"] = execution_decision.timeout_retry_used
    debug_meta["routing_failure_reason"] = str(decision_state.failure_reason or "")
    agentic_selection_blockers = list(getattr(execution_decision, "selection_blockers", ()) or ())
    agentic_route_supported = bool(getattr(execution_decision, "route_supported", False))
    agentic_tool_first_candidate = bool(getattr(execution_decision, "tool_first_candidate", False))
    debug_meta["agentic_route_supported"] = agentic_route_supported
    debug_meta["agentic_tool_first_candidate"] = agentic_tool_first_candidate
    debug_meta["agentic_selection_blockers"] = list(agentic_selection_blockers)
    debug_meta["agentic"] = {
        "selected": execution_decision.execution_mode == "agentic",
        "selection_reason": execution_decision.reason,
        "selection_source": execution_decision.selection_source,
        "feature_enabled": execution_decision.feature_enabled,
        "channel_allowed": execution_decision.channel_allowed,
        "route_supported": agentic_route_supported,
        "tool_suitable": execution_decision.tool_suitable,
        "tool_first_candidate": agentic_tool_first_candidate,
        "selection_blockers": list(agentic_selection_blockers),
        "llm_reason": execution_decision.llm_reason,
        "llm_confidence": execution_decision.llm_confidence,
        "llm_workflow": execution_decision.llm_workflow,
        "llm_execution_mode": execution_decision.llm_execution_mode,
        "confidence_gate_applied": execution_decision.confidence_gate_applied,
        "timeout_retry_used": execution_decision.timeout_retry_used,
        "used_tools": False,
        "trace": [],
        "fallback_to_component": False,
    }

    context.trace.intent = str(decision_state.intent or "") or context.trace.intent
    context.trace.route = str(route_decision.workflow or "") or context.trace.route
    context.trace.workflow = str(decision_state.internal_workflow or "") or context.trace.workflow
    context.trace.execution_mode = str(execution_mode or "") or context.trace.execution_mode
    context.trace.metadata["agentic_selection"] = {
        "selected": execution_decision.execution_mode == "agentic",
        "feature_enabled": bool(execution_decision.feature_enabled),
        "channel_allowed": bool(execution_decision.channel_allowed),
        "route_supported": agentic_route_supported,
        "tool_suitable": bool(execution_decision.tool_suitable),
        "tool_first_candidate": agentic_tool_first_candidate,
        "selection_blockers": list(agentic_selection_blockers),
    }
    if bool(route_decision.needs_clarification):
        context.trace.clarification_required = True
        context.trace.clarification_reason = str(
            decision_state.missing_slot
            or decision_state.failure_reason
            or route_decision.reason
            or ""
        ).strip() or context.trace.clarification_reason
    context.trace.set_timing(
        "route",
        (time.perf_counter() - context.step_started) * 1000.0,
    )

    return HarnessRouteResult(
        decision_state=decision_state,
        route_decision=route_decision,
        execution_decision=execution_decision,
        public_routing=public_routing,
        selection_source=selection_source,
        execution_mode=execution_mode,
    )
