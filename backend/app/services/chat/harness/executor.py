from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Any

from app.services.chat.harness.context import ChatHarnessContext, ChatHarnessDependencies
from app.services.chat.harness.router import HarnessRouteResult
from app.services.chat.harness.understanding import HarnessUnderstandingResult


_AGENTIC_GROUNDING_FALLBACK_STATUSES = {
    "fallback",
    "failed",
    "unsafe",
    "weak",
    "unrelated",
    "error",
}
_AGENTIC_GROUNDING_FALLBACK_ACTIONS = {
    "fallback",
    "clarify",
}


@dataclass(frozen=True)
class HarnessExecutionResult:
    path: str
    agentic_result: Any = None
    component_result: Any = None


async def run_execution(
    *,
    context: ChatHarnessContext,
    dependencies: ChatHarnessDependencies,
    understanding_result: HarnessUnderstandingResult,
    route_result: HarnessRouteResult,
) -> HarnessExecutionResult:
    context.current_step = "execute"
    context.step_started = time.perf_counter()

    if route_result.execution_mode == "agentic" and route_result.execution_decision is not None:
        agentic_result = await _run_agentic_path(
            context=context,
            dependencies=dependencies,
            understanding_result=understanding_result,
            route_result=route_result,
        )
        if agentic_result is not None:
            return agentic_result

    component_started = time.perf_counter()
    component_result = await context.service._run_component_pipeline(
        request=context.request,
        conversation_id=context.conversation_id_value,
        run_id=context.run_id,
        route_decision_override=route_result.route_decision,
        detail_override=understanding_result.detail,
        llm_call_count_override=int(understanding_result.understanding.llm_call_count or 0)
        + int(understanding_result.detail_llm_calls or 0),
        routing_selection_source=route_result.selection_source,
        internal_workflow_override=route_result.decision_state.internal_workflow,
        decision_state_override=route_result.decision_state,
        channel=context.channel,
    )
    context.service._add_latency_span(
        context.spans,
        "component_pipeline_ms",
        (time.perf_counter() - component_started) * 1000.0,
    )
    context.trace.set_timing(
        "execute",
        (time.perf_counter() - context.step_started) * 1000.0,
    )
    return HarnessExecutionResult(path="component", component_result=component_result)


async def _run_agentic_path(
    *,
    context: ChatHarnessContext,
    dependencies: ChatHarnessDependencies,
    understanding_result: HarnessUnderstandingResult,
    route_result: HarnessRouteResult,
) -> HarnessExecutionResult | None:
    agentic_search_plan = dependencies.build_search_plan(
        user_text=context.user_text,
        workflow=route_result.route_decision.workflow,
        detail=understanding_result.detail,
        sku_tokens=understanding_result.sku_tokens,
        knowledge_query=str(route_result.route_decision.knowledge_query or ""),
    )
    expected_tool_groups = _expected_tool_groups(agentic_search_plan)
    expected_tools = _expected_tools(agentic_search_plan, expected_tool_groups)
    _record_agentic_tool_expectations(
        context=context,
        expected_tools=expected_tools,
        expected_tool_groups=expected_tool_groups,
        actual_tools=[],
        missing_expected_tools=[],
        expected_tool_missing=False,
    )
    agentic_started = time.perf_counter()
    agentic_result = None
    agentic_error: Exception | None = None
    try:
        agentic_kwargs = {
            "user_text": context.user_text,
            "conversation_id": context.conversation_id_value,
            "run_id": context.run_id,
            "channel": context.channel,
            "reply_language": str(context.request.locale or "en-US"),
        }
        try:
            signature = inspect.signature(context.service._run_agentic_workflow)
            if "search_plan" in signature.parameters:
                agentic_kwargs["search_plan"] = agentic_search_plan
        except Exception:
            agentic_kwargs["search_plan"] = agentic_search_plan
        agentic_result = await context.service._run_agentic_workflow(**agentic_kwargs)
    except Exception as exc:
        agentic_error = exc
        context.debug_meta["agentic_error"] = str(exc)
        context.debug_meta["agentic_failure_reason"] = f"agentic_failed:{type(exc).__name__}"
    context.service._add_latency_span(
        context.spans,
        "agentic_orchestrator_ms",
        (time.perf_counter() - agentic_started) * 1000.0,
    )
    normalized_agentic_result = dependencies.coerce_agentic_result(agentic_result)
    actual_tools = _agentic_actual_tools(normalized_agentic_result)
    missing_expected_tools = _missing_expected_tools(
        expected_tool_groups=expected_tool_groups,
        actual_tools=actual_tools,
    )
    expected_tool_missing = _should_fallback_for_expected_tool_missing(
        agentic_result=normalized_agentic_result,
        actual_tools=actual_tools,
        missing_expected_tools=missing_expected_tools,
    )
    _record_agentic_tool_expectations(
        context=context,
        expected_tools=expected_tools,
        expected_tool_groups=expected_tool_groups,
        actual_tools=actual_tools,
        missing_expected_tools=missing_expected_tools,
        expected_tool_missing=expected_tool_missing,
    )

    fallback_enabled = bool(context.capabilities.agentic_enable_fallback)
    if normalized_agentic_result.outcome == dependencies.AgentRunOutcome.TOOL_SUCCESS:
        if expected_tool_missing:
            if not fallback_enabled:
                raise RuntimeError("agentic expected tool missing")
            fallback_result = normalized_agentic_result
            fallback_result.fallback_reason = "agentic_expected_tool_missing"
            context.debug_meta["agentic_failure_reason"] = dependencies.agentic_failure_reason(
                fallback_reason="agentic_expected_tool_missing",
                existing_failure_reason=str(context.debug_meta.get("agentic_failure_reason") or ""),
            )
            dependencies.apply_agentic_fallback_debug(
                debug_meta=context.debug_meta,
                agentic_result=fallback_result,
            )
            return None
        if _agentic_grounding_failed(normalized_agentic_result):
            if not fallback_enabled:
                raise RuntimeError("agentic grounding failed")
            fallback_result = normalized_agentic_result
            fallback_result.fallback_reason = "agentic_grounding_failed"
            context.debug_meta["agentic_failure_reason"] = dependencies.agentic_failure_reason(
                fallback_reason="agentic_grounding_failed",
                existing_failure_reason=str(context.debug_meta.get("agentic_failure_reason") or ""),
            )
            dependencies.apply_agentic_fallback_debug(
                debug_meta=context.debug_meta,
                agentic_result=fallback_result,
            )
            return None
        dependencies.apply_agentic_success_debug(
            debug_meta=context.debug_meta,
            agentic_result=normalized_agentic_result,
        )
        context.trace.set_timing(
            "execute",
            (time.perf_counter() - context.step_started) * 1000.0,
        )
        return HarnessExecutionResult(path="agentic", agentic_result=normalized_agentic_result)

    fallback_result = normalized_agentic_result
    if agentic_error is not None and not fallback_enabled:
        raise agentic_error
    if agentic_error is not None:
        fallback_result = dependencies.coerce_agentic_result(agentic_result)
        fallback_result.fallback_reason = "agentic_error"
        context.debug_meta["agentic_failure_reason"] = dependencies.agentic_failure_reason(
            fallback_reason="agentic_error",
            existing_failure_reason=str(context.debug_meta.get("agentic_failure_reason") or ""),
        )
    elif expected_tool_missing:
        fallback_result.fallback_reason = "agentic_expected_tool_missing"
        context.debug_meta["agentic_failure_reason"] = dependencies.agentic_failure_reason(
            fallback_reason="agentic_expected_tool_missing",
            existing_failure_reason=str(context.debug_meta.get("agentic_failure_reason") or ""),
        )
    dependencies.apply_agentic_fallback_debug(
        debug_meta=context.debug_meta,
        agentic_result=fallback_result,
    )
    if normalized_agentic_result.outcome == dependencies.AgentRunOutcome.EMPTY and not fallback_enabled:
        raise RuntimeError("agentic workflow returned no result")
    return None


def _expected_tool_groups(search_plan: Any) -> list[list[str]]:
    try:
        groups = search_plan.expected_tool_groups()
    except Exception:
        groups = []
    normalized_groups: list[list[str]] = []
    for raw_group in list(groups or []):
        if isinstance(raw_group, (list, tuple, set)):
            group = [
                str(tool_name or "").strip()
                for tool_name in list(raw_group)
                if str(tool_name or "").strip()
            ]
        else:
            group = [str(raw_group or "").strip()] if str(raw_group or "").strip() else []
        if group:
            normalized_groups.append(group)
    return normalized_groups


def _expected_tools(search_plan: Any, expected_tool_groups: list[list[str]]) -> list[str]:
    try:
        tools = list(search_plan.expected_tools() or [])
    except Exception:
        tools = [tool_name for group in expected_tool_groups for tool_name in group]
    expected: list[str] = []
    for tool_name in tools:
        clean_tool = str(tool_name or "").strip()
        if clean_tool and clean_tool not in expected:
            expected.append(clean_tool)
    return expected


def _agentic_actual_tools(agentic_result: Any) -> list[str]:
    actual: list[str] = []
    for raw in list(getattr(agentic_result, "trace", []) or []):
        if not isinstance(raw, dict):
            continue
        tool_name = str(raw.get("tool") or raw.get("name") or "").strip()
        if tool_name and tool_name not in actual:
            actual.append(tool_name)
    return actual


def _missing_expected_tools(
    *,
    expected_tool_groups: list[list[str]],
    actual_tools: list[str],
) -> list[str]:
    actual = {str(tool_name or "").strip() for tool_name in list(actual_tools or []) if str(tool_name or "").strip()}
    missing: list[str] = []
    for group in list(expected_tool_groups or []):
        clean_group = [
            str(tool_name or "").strip()
            for tool_name in list(group or [])
            if str(tool_name or "").strip()
        ]
        if clean_group and not any(tool_name in actual for tool_name in clean_group):
            missing.append("|".join(clean_group))
    return missing


def _should_fallback_for_expected_tool_missing(
    *,
    agentic_result: Any,
    actual_tools: list[str],
    missing_expected_tools: list[str],
) -> bool:
    if not missing_expected_tools:
        return False
    final_reply = str(getattr(agentic_result, "final_reply", "") or "").strip()
    return bool(final_reply or actual_tools)


def _record_agentic_tool_expectations(
    *,
    context: ChatHarnessContext,
    expected_tools: list[str],
    expected_tool_groups: list[list[str]],
    actual_tools: list[str],
    missing_expected_tools: list[str],
    expected_tool_missing: bool,
) -> None:
    agentic_debug = context.debug_meta.setdefault("agentic", {})
    if not isinstance(agentic_debug, dict):
        agentic_debug = {}
        context.debug_meta["agentic"] = agentic_debug
    payload = {
        "expected_tools": list(expected_tools or []),
        "expected_tool_groups": [list(group or []) for group in list(expected_tool_groups or [])],
        "actual_tools": list(actual_tools or []),
        "missing_expected_tools": list(missing_expected_tools or []),
        "expected_tool_missing": bool(expected_tool_missing),
    }
    agentic_debug.update(payload)
    context.trace.metadata["agentic_tool_expectations"] = dict(payload)
    selection = context.trace.metadata.setdefault("agentic_selection", {})
    if isinstance(selection, dict):
        selection.update(payload)


def _agentic_grounding_failed(agentic_result: Any) -> bool:
    grounding = getattr(agentic_result, "grounding", None)
    if not isinstance(grounding, dict) or not grounding:
        return False
    payloads: list[dict[str, Any]] = [grounding]
    for key in ("catalog", "knowledge"):
        nested = grounding.get(key)
        if isinstance(nested, dict):
            payloads.append(nested)

    for payload in payloads:
        status = str(payload.get("status") or "").strip().lower()
        if status in _AGENTIC_GROUNDING_FALLBACK_STATUSES:
            return True
        action = str(payload.get("safe_customer_action") or "").strip().lower()
        if action in _AGENTIC_GROUNDING_FALLBACK_ACTIONS:
            return True
    return False
