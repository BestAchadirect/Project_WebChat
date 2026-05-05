from __future__ import annotations

from typing import Any, Dict

from app.schemas.chat import (
    ChatComponent,
    ChatResponse,
    ChatResponseMeta,
    ChatRouting,
    assistant_message_component,
    product_cards_component,
    quick_replies_component,
)
from app.services.chat.agentic.orchestrator import AgentRunOutcome, AgentRunResult
from app.services.chat.runtime.fallback_policy import (
    agentic_failure_reason,
    build_fallback_debug,
)


def _agentic_outcome_value(agentic_result: Any) -> str:
    return str(getattr(getattr(agentic_result, "outcome", ""), "value", getattr(agentic_result, "outcome", "")) or "")


def build_agentic_response(
    *,
    conversation_id: int,
    routing: ChatRouting,
    query_summary: str,
    agentic_result: Any,
) -> ChatResponse:
    normalized = coerce_agentic_result(agentic_result)
    assistant_text = str(normalized.final_reply or "").strip()
    product_carousel = list(normalized.product_carousel or [])
    follow_up_questions = [
        str(item or "").strip()
        for item in list(normalized.follow_up_questions or [])
        if str(item or "").strip()
    ]
    components: list[ChatComponent] = []
    assistant_component = assistant_message_component(assistant_text)
    if assistant_component is not None:
        components.append(assistant_component)
    product_component = product_cards_component(product_carousel)
    if product_component is not None:
        components.append(product_component)
    quick_replies = quick_replies_component(list(follow_up_questions))
    if quick_replies is not None:
        components.append(quick_replies)
    return ChatResponse(
        conversation_id=conversation_id,
        reply_text=assistant_text,
        carousel_msg=str(normalized.carousel_msg or ""),
        product_carousel=product_carousel,
        routing=routing,
        sources=list(normalized.sources or []),
        debug={},
        components=components,
        meta=ChatResponseMeta(
            query_summary=str(query_summary or ""),
            latency_ms=0.0,
            source="tool",
            llm_calls=0,
            embedding_calls=0,
            product_result_count=len(product_carousel),
            product_display_count=len(product_carousel),
            product_has_more=False,
        ),
    )


def apply_agentic_success_debug(*, debug_meta: Dict[str, Any], agentic_result: Any) -> None:
    outcome = _agentic_outcome_value(agentic_result)
    debug_meta["workflow_path"] = "agentic_primary"
    debug_meta["component_mode"] = "agentic"
    debug_meta["component_plan"] = ["agentic_workflow"]
    debug_meta["component_source"] = "tool"
    debug_meta["external_call_counts"] = {}
    debug_meta["external_call_count"] = int(len(list(getattr(agentic_result, "trace", []) or [])))
    debug_meta["llm_call_count"] = 0
    debug_meta["agentic"] = {
        **dict(debug_meta.get("agentic") or {}),
        "outcome": str(outcome or AgentRunOutcome.TOOL_SUCCESS.value),
        "used_tools": True,
        "trace": list(getattr(agentic_result, "trace", []) or []),
        "grounding": dict(getattr(agentic_result, "grounding", {}) or {}),
        "fallback_to_component": False,
    }
    grounding = dict(getattr(agentic_result, "grounding", {}) or {})
    if grounding:
        debug_meta["agentic_grounding"] = grounding


def coerce_agentic_result(agentic_result: Any) -> AgentRunResult:
    if isinstance(agentic_result, AgentRunResult):
        return agentic_result
    if agentic_result is None:
        return AgentRunResult.empty()
    return AgentRunResult(
        final_reply=str(getattr(agentic_result, "final_reply", "") or ""),
        used_tools=bool(getattr(agentic_result, "used_tools", False)),
        product_carousel=list(getattr(agentic_result, "product_carousel", []) or []),
        sources=list(getattr(agentic_result, "sources", []) or []),
        follow_up_questions=list(getattr(agentic_result, "follow_up_questions", []) or []),
        carousel_msg=str(getattr(agentic_result, "carousel_msg", "") or ""),
        trace=list(getattr(agentic_result, "trace", []) or []),
        grounding=dict(getattr(agentic_result, "grounding", {}) or {}),
        outcome=str(getattr(agentic_result, "outcome", "") or ""),
        fallback_reason=str(getattr(agentic_result, "fallback_reason", "") or ""),
    )


def apply_agentic_fallback_debug(*, debug_meta: Dict[str, Any], agentic_result: Any) -> None:
    normalized = coerce_agentic_result(agentic_result)
    fallback_reason = str(normalized.fallback_reason or "empty_result")
    failure_reason = agentic_failure_reason(
        fallback_reason=fallback_reason,
        existing_failure_reason=str(debug_meta.get("agentic_failure_reason") or ""),
    )
    debug_meta["agentic"] = {
        **dict(debug_meta.get("agentic") or {}),
        **build_fallback_debug(
            fallback_reason=fallback_reason,
            failure_reason=failure_reason,
            outcome=str(_agentic_outcome_value(normalized) or AgentRunOutcome.EMPTY.value),
            used_tools=bool(normalized.used_tools),
            trace=list(normalized.trace or []),
            final_reply_present=bool(str(normalized.final_reply or "").strip()),
        ),
    }
