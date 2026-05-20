from __future__ import annotations

import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.schemas.chat import ChatComponent, ChatResponse, ChatResponseMeta, ChatRouting
from app.services.ai.llm_service import llm_service
from app.services.chat.agentic.orchestrator import AgentRunOutcome
from app.services.chat.harness.context import ChatHarnessContext
from app.services.chat.harness.executor import HarnessExecutionResult
from app.services.chat.harness.router import HarnessRouteResult
from app.services.chat.harness.trace import HarnessTrace, attach_harness_trace
from app.services.chat.runtime.agentic_adapter import build_agentic_response, coerce_agentic_result
from app.services.chat.runtime.fallback_policy import runtime_failure_reason


@dataclass(frozen=True)
class HarnessFinalizedResult:
    response: ChatResponse
    detail_mode_enabled: bool = False


async def run_finalization(
    *,
    context: ChatHarnessContext,
    dependencies: Any = None,
    route_result: HarnessRouteResult,
    execution_result: HarnessExecutionResult,
) -> HarnessFinalizedResult:
    del dependencies
    context.current_step = "finalize"
    context.step_started = time.perf_counter()
    if execution_result.path == "agentic":
        response = await _finalize_agentic_response(
            context=context,
            routing=route_result.public_routing,
            agentic_result=execution_result.agentic_result,
        )
        context.trace.set_timing(
            "finalize",
            (time.perf_counter() - context.step_started) * 1000.0,
        )
        _refresh_response_trace(context=context, response=response)
        return HarnessFinalizedResult(response=response, detail_mode_enabled=False)

    response, detail_mode_enabled = await _finalize_component_response(
        context=context,
        component_result=execution_result.component_result,
    )
    context.detail_mode_enabled = bool(detail_mode_enabled)
    context.trace.set_timing(
        "finalize",
        (time.perf_counter() - context.step_started) * 1000.0,
    )
    _refresh_response_trace(context=context, response=response)
    return HarnessFinalizedResult(
        response=response,
        detail_mode_enabled=bool(detail_mode_enabled),
    )


async def run_error_finalization(
    *,
    context: ChatHarnessContext,
    dependencies: Any = None,
    error: Exception,
) -> HarnessFinalizedResult:
    del dependencies
    context.trace.add_error(str(error))
    if context.current_step and context.current_step not in context.trace.timings_ms:
        context.trace.set_timing(
            context.current_step,
            (time.perf_counter() - context.step_started) * 1000.0,
        )
    try:
        if hasattr(context.service.db, "rollback"):
            await context.service.db.rollback()
            context.debug_meta["component_pipeline_rollback"] = True
    except Exception as rollback_exc:
        context.debug_meta["component_pipeline_rollback"] = False
        context.debug_meta["component_pipeline_rollback_error"] = str(rollback_exc)

    context.debug_meta["component_mode"] = "error"
    context.debug_meta["component_pipeline_error"] = str(error)
    context.current_step = "finalize"
    context.step_started = time.perf_counter()
    response = await _finalize_runtime_error(
        context=context,
        error=error,
    )
    context.trace.set_timing(
        "finalize",
        (time.perf_counter() - context.step_started) * 1000.0,
    )
    _refresh_response_trace(context=context, response=response)
    return HarnessFinalizedResult(
        response=response,
        detail_mode_enabled=context.detail_mode_enabled,
    )


def _refresh_response_trace(*, context: ChatHarnessContext, response: ChatResponse) -> None:
    context.trace.update_from_response(response)
    response.debug = dict(response.debug or {})
    response.debug["harness_trace"] = context.trace.to_dict()


def _apply_component_debug(*, debug_meta: dict[str, Any], component_result: Any) -> None:
    debug_meta.update(dict(getattr(component_result, "debug", {}) or {}))
    debug_meta["component_mode"] = "primary"
    debug_meta["component_plan"] = list(debug_meta.get("component_plan") or [])
    external_call_counts = dict(getattr(component_result, "external_call_counts", {}) or {})
    debug_meta["external_call_counts"] = external_call_counts
    debug_meta["external_call_count"] = int(sum(external_call_counts.values()))
    debug_meta["llm_call_count"] = int(getattr(component_result, "llm_calls", 0) or 0)


def apply_component_debug(*, debug_meta: dict[str, Any], component_result: Any) -> None:
    _apply_component_debug(debug_meta=debug_meta, component_result=component_result)


async def finalize_component_response(
    service: Any,
    *,
    component_result: Any,
    conversation_id: int,
    user_text: str,
    channel: str,
    run_id: str,
    debug_meta: dict[str, Any],
    spans: dict[str, Any],
    total_started: float,
    trace: HarnessTrace | None = None,
) -> tuple[ChatResponse, bool]:
    context = _compat_context(
        service=service,
        conversation_id=conversation_id,
        user_text=user_text,
        channel=channel,
        run_id=run_id,
        debug_meta=debug_meta,
        spans=spans,
        total_started=total_started,
        trace=trace,
    )
    return await _finalize_component_response(context=context, component_result=component_result)


async def _finalize_component_response(
    *,
    context: ChatHarnessContext,
    component_result: Any,
) -> tuple[ChatResponse, bool]:
    detail_mode_enabled = bool(getattr(component_result, "detail_mode_triggered", False))
    for span_key, span_value in dict(getattr(component_result, "spans", {}) or {}).items():
        context.service._add_latency_span(context.spans, str(span_key), float(span_value or 0.0))
    _apply_component_debug(debug_meta=context.debug_meta, component_result=component_result)
    attach_harness_trace(
        debug_meta=context.debug_meta,
        trace=context.trace,
        response=component_result.response,
    )
    token_usage = llm_service.consume_token_usage()
    response = await context.service._finalize_with_latency(
        conversation_id=context.conversation_id_value,
        user_text=context.user_text,
        response=component_result.response,
        token_usage=token_usage if isinstance(token_usage, dict) else None,
        channel=context.channel,
        run_id=context.run_id,
        debug_meta=context.debug_meta,
        spans=context.spans,
        total_started=context.total_started,
        detail_mode_triggered=detail_mode_enabled,
        conversation_state=getattr(component_result, "conversation_state", None),
    )
    return response, detail_mode_enabled


async def _finalize_agentic_response(
    *,
    context: ChatHarnessContext,
    routing: ChatRouting,
    agentic_result: Any,
    query_summary: str | None = None,
) -> ChatResponse:
    normalized_agentic_result = coerce_agentic_result(agentic_result)
    if normalized_agentic_result.outcome != AgentRunOutcome.TOOL_SUCCESS:
        raise ValueError(
            "finalize_agentic_response requires tool_success outcome, "
            f"got {normalized_agentic_result.outcome.value}"
        )
    response = build_agentic_response(
        conversation_id=context.conversation_id_value,
        routing=routing,
        query_summary=context.user_text if query_summary is None else query_summary,
        agentic_result=normalized_agentic_result,
    )
    attach_harness_trace(
        debug_meta=context.debug_meta,
        trace=context.trace,
        response=response,
    )
    token_usage = llm_service.consume_token_usage()
    return await context.service._finalize_with_latency(
        conversation_id=context.conversation_id_value,
        user_text=context.user_text,
        response=response,
        token_usage=token_usage if isinstance(token_usage, dict) else None,
        channel=context.channel,
        run_id=context.run_id,
        debug_meta=context.debug_meta,
        spans=context.spans,
        total_started=context.total_started,
        detail_mode_triggered=False,
    )


async def finalize_agentic_response(
    service: Any,
    *,
    conversation_id: int,
    routing: ChatRouting,
    query_summary: str,
    agentic_result: Any,
    user_text: str,
    channel: str,
    run_id: str,
    debug_meta: dict[str, Any],
    spans: dict[str, Any],
    total_started: float,
    trace: HarnessTrace | None = None,
) -> ChatResponse:
    context = _compat_context(
        service=service,
        conversation_id=conversation_id,
        user_text=user_text,
        channel=channel,
        run_id=run_id,
        debug_meta=debug_meta,
        spans=spans,
        total_started=total_started,
        trace=trace,
    )
    return await _finalize_agentic_response(
        context=context,
        routing=routing,
        query_summary=query_summary,
        agentic_result=agentic_result,
    )


def _build_runtime_error_response(*, conversation_id: int, query_summary: str) -> ChatResponse:
    return ChatResponse(
        conversation_id=conversation_id,
        reply_text="I could not process that request right now.",
        carousel_msg="",
        product_carousel=[],
        routing=ChatRouting(
            workflow="fallback",
            execution_mode="component",
            needs_clarification=True,
            reason="runtime_error",
            selection_source="llm_fallback",
        ),
        sources=[],
        debug={},
        components=[
            ChatComponent(
                type="error",
                data={"message": "I could not process that request right now."},
            )
        ],
        meta=ChatResponseMeta(
            query_summary=query_summary,
            latency_ms=0.0,
            source="error",
            llm_calls=0,
            embedding_calls=0,
            product_result_count=0,
            product_display_count=0,
            product_has_more=False,
        ),
    )


def build_runtime_error_response(*, conversation_id: int, query_summary: str) -> ChatResponse:
    return _build_runtime_error_response(
        conversation_id=conversation_id,
        query_summary=query_summary,
    )


async def finalize_runtime_error(
    service: Any,
    *,
    error: Exception,
    conversation_id: int,
    user_text: str,
    channel: str,
    run_id: str,
    debug_meta: dict[str, Any],
    spans: dict[str, Any],
    total_started: float,
    detail_mode_triggered: bool,
    trace: HarnessTrace | None = None,
) -> ChatResponse:
    context = _compat_context(
        service=service,
        conversation_id=conversation_id,
        user_text=user_text,
        channel=channel,
        run_id=run_id,
        debug_meta=debug_meta,
        spans=spans,
        total_started=total_started,
        detail_mode_triggered=detail_mode_triggered,
        trace=trace,
    )
    return await _finalize_runtime_error(context=context, error=error)


async def _finalize_runtime_error(
    *,
    context: ChatHarnessContext,
    error: Exception,
) -> ChatResponse:
    context.debug_meta["runtime_failure_reason"] = runtime_failure_reason(error=error)
    token_usage = llm_service.consume_token_usage()
    context.service._log_latency_error(
        run_id=context.run_id,
        debug_meta=context.debug_meta,
        spans=context.spans,
        total_started=context.total_started,
        detail_mode_triggered=context.detail_mode_enabled,
        token_usage=token_usage if isinstance(token_usage, dict) else None,
        error=error,
    )
    error_response = _build_runtime_error_response(
        conversation_id=context.conversation_id_value,
        query_summary=context.user_text,
    )
    attach_harness_trace(
        debug_meta=context.debug_meta,
        trace=context.trace,
        response=error_response,
    )
    return await context.service._finalize_with_latency(
        conversation_id=context.conversation_id_value,
        user_text=context.user_text,
        response=error_response,
        token_usage=token_usage if isinstance(token_usage, dict) else None,
        channel=context.channel,
        run_id=context.run_id,
        debug_meta=context.debug_meta,
        spans=context.spans,
        total_started=context.total_started,
        detail_mode_triggered=context.detail_mode_enabled,
    )


def _compat_context(
    *,
    service: Any,
    conversation_id: int,
    user_text: str,
    channel: str,
    run_id: str,
    debug_meta: dict[str, Any],
    spans: dict[str, Any],
    total_started: float,
    detail_mode_triggered: bool = False,
    trace: HarnessTrace | None = None,
) -> ChatHarnessContext:
    clean_user_text = str(user_text or "")
    return ChatHarnessContext(
        service=service,
        request=SimpleNamespace(
            message=clean_user_text,
            user_id="",
            conversation_id=conversation_id,
            locale="",
        ),
        channel=str(channel or ""),
        trace=trace
        or HarnessTrace(
            run_id=run_id,
            conversation_id=str(conversation_id) if conversation_id else None,
            user_message=clean_user_text,
        ),
        run_id=run_id,
        user_text=clean_user_text,
        conversation_id_value=int(conversation_id or 0),
        total_started=total_started,
        spans=spans,
        capabilities=SimpleNamespace(),
        debug_meta=debug_meta,
        current_step="finalize",
        step_started=time.perf_counter(),
        detail_mode_enabled=bool(detail_mode_triggered),
    )
