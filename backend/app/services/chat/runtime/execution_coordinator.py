from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.schemas.chat import ChatComponent, ChatResponse, ChatResponseMeta, ChatRouting
from app.services.ai.llm_service import llm_service
from app.services.chat.agentic.orchestrator import AgentRunOutcome
from app.services.chat.runtime.agentic_adapter import build_agentic_response, coerce_agentic_result
from app.services.chat.runtime.fallback_policy import runtime_failure_reason


def build_initial_debug_meta(*, channel: str, config_fingerprint: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "run_id": "",
        "workflow_path": "component_primary",
        "channel": channel,
        "config_fingerprint": config_fingerprint,
        "openai_timeout_seconds": float(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 12.0)),
        "openai_max_retries": int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
        "component_mode": "primary",
        "component_channel_allowed": True,
    }


def safe_conversation_id(conv: Any, fallback: int = 0) -> int:
    try:
        return int(getattr(conv, "id", 0) or 0)
    except Exception:
        return int(fallback or 0)


def apply_component_debug(*, debug_meta: Dict[str, Any], component_result: Any) -> None:
    debug_meta.update(dict(getattr(component_result, "debug", {}) or {}))
    debug_meta["component_mode"] = "primary"
    debug_meta["component_plan"] = list(debug_meta.get("component_plan") or [])
    external_call_counts = dict(getattr(component_result, "external_call_counts", {}) or {})
    debug_meta["external_call_counts"] = external_call_counts
    debug_meta["external_call_count"] = int(sum(external_call_counts.values()))
    debug_meta["llm_call_count"] = int(getattr(component_result, "llm_calls", 0) or 0)


async def finalize_component_response(
    service: Any,
    *,
    component_result: Any,
    conversation_id: int,
    user_text: str,
    channel: str,
    run_id: str,
    debug_meta: Dict[str, Any],
    spans: Dict[str, Any],
    total_started: float,
) -> Tuple[ChatResponse, bool]:
    detail_mode_enabled = bool(getattr(component_result, "detail_mode_triggered", False))
    for span_key, span_value in dict(getattr(component_result, "spans", {}) or {}).items():
        service._add_latency_span(spans, str(span_key), float(span_value or 0.0))
    apply_component_debug(debug_meta=debug_meta, component_result=component_result)
    token_usage = llm_service.consume_token_usage()
    response = await service._finalize_with_latency(
        conversation_id=conversation_id,
        user_text=user_text,
        response=component_result.response,
        token_usage=token_usage if isinstance(token_usage, dict) else None,
        channel=channel,
        run_id=run_id,
        debug_meta=debug_meta,
        spans=spans,
        total_started=total_started,
        detail_mode_triggered=detail_mode_enabled,
        conversation_state=getattr(component_result, "conversation_state", None),
    )
    return response, detail_mode_enabled


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
    debug_meta: Dict[str, Any],
    spans: Dict[str, Any],
    total_started: float,
) -> ChatResponse:
    normalized_agentic_result = coerce_agentic_result(agentic_result)
    if normalized_agentic_result.outcome != AgentRunOutcome.TOOL_SUCCESS:
        raise ValueError(
            f"finalize_agentic_response requires tool_success outcome, got {normalized_agentic_result.outcome.value}"
        )
    response = build_agentic_response(
        conversation_id=conversation_id,
        routing=routing,
        query_summary=query_summary,
        agentic_result=normalized_agentic_result,
    )
    token_usage = llm_service.consume_token_usage()
    return await service._finalize_with_latency(
        conversation_id=conversation_id,
        user_text=user_text,
        response=response,
        token_usage=token_usage if isinstance(token_usage, dict) else None,
        channel=channel,
        run_id=run_id,
        debug_meta=debug_meta,
        spans=spans,
        total_started=total_started,
        detail_mode_triggered=False,
    )


def build_runtime_error_response(*, conversation_id: int, query_summary: str) -> ChatResponse:
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


async def finalize_runtime_error(
    service: Any,
    *,
    error: Exception,
    conversation_id: int,
    user_text: str,
    channel: str,
    run_id: str,
    debug_meta: Dict[str, Any],
    spans: Dict[str, Any],
    total_started: float,
    detail_mode_triggered: bool,
) -> ChatResponse:
    debug_meta["runtime_failure_reason"] = runtime_failure_reason(error=error)
    token_usage = llm_service.consume_token_usage()
    service._log_latency_error(
        run_id=run_id,
        debug_meta=debug_meta,
        spans=spans,
        total_started=total_started,
        detail_mode_triggered=detail_mode_triggered,
        token_usage=token_usage if isinstance(token_usage, dict) else None,
        error=error,
    )
    error_response = build_runtime_error_response(
        conversation_id=conversation_id,
        query_summary=user_text,
    )
    return await service._finalize_with_latency(
        conversation_id=conversation_id,
        user_text=user_text,
        response=error_response,
        token_usage=token_usage if isinstance(token_usage, dict) else None,
        channel=channel,
        run_id=run_id,
        debug_meta=debug_meta,
        spans=spans,
        total_started=total_started,
        detail_mode_triggered=detail_mode_triggered,
    )
