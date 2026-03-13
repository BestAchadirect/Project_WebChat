from typing import Any, Dict, Iterable, List, Optional

from app.schemas.chat import ChatResponse


def derive_response_status(*, response: ChatResponse) -> str:
    reply_text = str(getattr(response, "reply_text", "") or "").strip().lower()
    if not reply_text:
        return "no_answer"
    workflow = str(getattr(getattr(response, "routing", None), "workflow", "") or "").strip().lower()
    if workflow == "fallback":
        return "fallback"
    if "don't have enough information" in reply_text:
        return "fallback"
    if "could not process this request" in reply_text:
        return "failed"
    return "success"


def build_chat_qa_metrics(
    *,
    user_text: str,
    response: ChatResponse,
    channel: Optional[str],
) -> Dict[str, Any]:
    debug = dict(getattr(response, "debug", {}) or {})
    retrieval_gate = debug.get("retrieval_gate") if isinstance(debug.get("retrieval_gate"), dict) else {}
    latency = debug.get("latency_spans") if isinstance(debug.get("latency_spans"), dict) else {}
    agentic = debug.get("agentic") if isinstance(debug.get("agentic"), dict) else {}
    meta = getattr(response, "meta", None)
    meta_source = getattr(meta, "source", None) if meta is not None else None
    routing = getattr(response, "routing", None)
    response_workflow = str(getattr(routing, "workflow", "") or "").strip()
    normalized_status = derive_response_status(response=response)
    action_kind = ""
    action_completed = bool(agentic.get("used_tools", False))

    if action_completed:
        action_kind = "agentic_tools"

    return {
        "question_length": len(str(user_text or "").strip()),
        "workflow": str(debug.get("workflow") or response_workflow or "").strip(),
        "response_workflow": response_workflow,
        "route": str(debug.get("workflow_path") or "").strip(),
        "status": normalized_status,
        "channel": str(channel or "").strip() or None,
        "component_mode": str(debug.get("component_mode") or "legacy"),
        "retrieval_source": str(
            debug.get("component_source")
            or debug.get("workflow_source")
            or meta_source
            or ""
        ).strip() or None,
        "reply_mode": str(debug.get("reply_mode") or "").strip() or None,
        "recommendation_mode": str(debug.get("recommendation_mode") or "").strip() or None,
        "action_kind": action_kind or None,
        "action_completed": bool(action_completed),
        "has_products": bool(response.product_carousel),
        "product_count": len(list(response.product_carousel or [])),
        "has_sources": bool(response.sources),
        "source_count": len(list(response.sources or [])),
        "follow_up_count": len(list(response.follow_up_questions or [])),
        "use_products": bool(retrieval_gate.get("use_products", False)),
        "use_knowledge": bool(retrieval_gate.get("use_knowledge", False)),
        "is_policy_like": bool(retrieval_gate.get("is_policy_like", False)),
        "agentic_used_tools": bool(agentic.get("used_tools", False)),
        "conversation_state_written": bool(debug.get("conversation_state_written", False)),
        "tone_repeat_hit": int(debug.get("tone_repeat_hit", 0) or 0),
        "tone_filler_stripped": int(debug.get("tone_filler_stripped", 0) or 0),
        "external_call_count": int(debug.get("external_call_count", 0) or 0),
        "llm_call_count": int(debug.get("llm_call_count", 0) or 0),
        "latency_total_ms": float(latency.get("total_ms", 0.0) or 0.0),
    }


def merge_token_usage_with_metrics(
    *,
    token_usage: Optional[Dict[str, Any]],
    chat_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    payload = dict(token_usage or {})
    payload["chat_metrics"] = dict(chat_metrics or {})
    return payload


def extract_chat_metrics(token_usage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = dict(token_usage or {})
    raw = payload.get("chat_metrics")
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def summarize_chat_metrics(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    totals_by_status: Dict[str, int] = {}
    totals_by_workflow: Dict[str, int] = {}
    totals_by_action: Dict[str, int] = {}
    action_completed = 0
    tone_repeat_hits = 0
    tone_filler_stripped = 0
    total_rows = 0

    for row in rows:
        metrics = dict(row or {})
        total_rows += 1
        status = str(metrics.get("status") or "unknown").strip() or "unknown"
        workflow = str(metrics.get("workflow") or "unknown").strip() or "unknown"
        action_kind = str(metrics.get("action_kind") or "").strip()
        totals_by_status[status] = totals_by_status.get(status, 0) + 1
        totals_by_workflow[workflow] = totals_by_workflow.get(workflow, 0) + 1
        if action_kind:
            totals_by_action[action_kind] = totals_by_action.get(action_kind, 0) + 1
        if bool(metrics.get("action_completed", False)):
            action_completed += 1
        tone_repeat_hits += int(metrics.get("tone_repeat_hit", 0) or 0)
        tone_filler_stripped += int(metrics.get("tone_filler_stripped", 0) or 0)

    return {
        "total_rows": total_rows,
        "by_status": dict(sorted(totals_by_status.items())),
        "by_workflow": dict(sorted(totals_by_workflow.items())),
        "by_action_kind": dict(sorted(totals_by_action.items())),
        "action_completed": action_completed,
        "tone_repeat_hit": tone_repeat_hits,
        "tone_filler_stripped": tone_filler_stripped,
    }
