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


def build_agentic_response(
    *,
    conversation_id: int,
    routing: ChatRouting,
    query_summary: str,
    agentic_result: Any,
) -> ChatResponse:
    assistant_text = str(getattr(agentic_result, "final_reply", "") or "").strip()
    product_carousel = list(getattr(agentic_result, "product_carousel", []) or [])
    follow_up_questions = [
        str(item or "").strip()
        for item in list(getattr(agentic_result, "follow_up_questions", []) or [])
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
        carousel_msg=str(getattr(agentic_result, "carousel_msg", "") or ""),
        product_carousel=product_carousel,
        routing=routing,
        sources=list(getattr(agentic_result, "sources", []) or []),
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
    debug_meta["workflow_path"] = "agentic_primary"
    debug_meta["component_mode"] = "agentic"
    debug_meta["component_plan"] = ["agentic_workflow"]
    debug_meta["component_source"] = "tool"
    debug_meta["external_call_counts"] = {}
    debug_meta["external_call_count"] = int(len(list(getattr(agentic_result, "trace", []) or [])))
    debug_meta["llm_call_count"] = 0
    debug_meta["agentic"] = {
        **dict(debug_meta.get("agentic") or {}),
        "used_tools": True,
        "trace": list(getattr(agentic_result, "trace", []) or []),
        "fallback_to_component": False,
    }


def apply_agentic_fallback_debug(*, debug_meta: Dict[str, Any], fallback_reason: str) -> None:
    failure_reason = str(debug_meta.get("agentic_failure_reason") or "")
    if not failure_reason and str(fallback_reason or "") == "no_tool_usage":
        failure_reason = "agentic_failed:no_tool_usage"
    elif not failure_reason and str(fallback_reason or "") == "empty_result":
        failure_reason = "agentic_failed:empty_result"
    debug_meta["agentic"] = {
        **dict(debug_meta.get("agentic") or {}),
        "fallback_to_component": True,
        "fallback_reason": str(fallback_reason or "empty_result"),
        "failure_reason": failure_reason,
    }
