from typing import Any, Dict, Iterable, List, Optional

from app.schemas.chat import ChatResponse
import app.services.chat.presentation.component_contract as component_contract


def derive_response_status(*, response: ChatResponse) -> str:
    reply_text = component_contract.assistant_text_from_response(response).strip().lower()
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
    grounding = debug.get("grounding") if isinstance(debug.get("grounding"), dict) else {}
    knowledge_grounding = debug.get("knowledge_grounding") if isinstance(debug.get("knowledge_grounding"), dict) else {}
    latency = debug.get("latency_spans") if isinstance(debug.get("latency_spans"), dict) else {}
    agentic = debug.get("agentic") if isinstance(debug.get("agentic"), dict) else {}
    conversation_state_enabled = bool(debug.get("conversation_state_enabled", False))
    conversation_state_written = bool(debug.get("conversation_state_written", False))
    conversation_state_filter_merge_applied = bool(
        debug.get("conversation_state_filter_merge_applied", False)
    )
    try:
        conversation_state_loaded_version = int(debug.get("conversation_state_loaded_version", 0) or 0)
    except Exception:
        conversation_state_loaded_version = 0
    meta = getattr(response, "meta", None)
    meta_source = getattr(meta, "source", None) if meta is not None else None
    routing = getattr(response, "routing", None)
    response_workflow = str(getattr(routing, "workflow", "") or "").strip()
    normalized_status = derive_response_status(response=response)
    action_kind = ""
    action_completed = bool(agentic.get("used_tools", False))
    response_products = component_contract.product_cards_from_response(response)
    response_follow_ups = component_contract.follow_up_questions_from_response(response)

    if action_completed:
        action_kind = "agentic_tools"

    return {
        "question_length": len(str(user_text or "").strip()),
        "workflow": str(debug.get("workflow") or response_workflow or "").strip(),
        "response_workflow": response_workflow,
        "route": str(debug.get("workflow_path") or "").strip(),
        "status": normalized_status,
        "channel": str(channel or "").strip() or None,
        "component_mode": str(debug.get("component_mode") or "unknown"),
        "retrieval_source": str(
            debug.get("component_source")
            or debug.get("workflow_source")
            or meta_source
            or ""
        ).strip() or None,
        "reply_mode": str(debug.get("reply_mode") or "").strip() or None,
        "action_kind": action_kind or None,
        "action_completed": bool(action_completed),
        "has_products": bool(response_products),
        "product_count": len(list(response_products or [])),
        "has_sources": bool(response.sources),
        "source_count": len(list(response.sources or [])),
        "follow_up_count": len(list(response_follow_ups or [])),
        "use_products": bool(retrieval_gate.get("use_products", False)),
        "use_knowledge": bool(retrieval_gate.get("use_knowledge", False)),
        "is_policy_like": bool(retrieval_gate.get("is_policy_like", False)),
        "grounding_status": str(
            grounding.get("status")
            or knowledge_grounding.get("status")
            or debug.get("grounding_status")
            or debug.get("knowledge_grounding_status")
            or ""
        ).strip() or None,
        "grounding_safe_action": str(
            grounding.get("safe_customer_action")
            or knowledge_grounding.get("safe_customer_action")
            or debug.get("grounding_safe_action")
            or debug.get("knowledge_grounding_safe_action")
            or ""
        ).strip() or None,
        "grounding_reason_count": len(
            list(
                grounding.get("reasons")
                or knowledge_grounding.get("reasons")
                or debug.get("grounding_reasons")
                or debug.get("knowledge_grounding_reasons")
                or []
            )
        ),
        "agentic_used_tools": bool(agentic.get("used_tools", False)),
        "conversation_state_written": bool(debug.get("conversation_state_written", False)),
        "conversation_state_enabled": conversation_state_enabled,
        "conversation_state_filter_merge_applied": conversation_state_filter_merge_applied,
        "conversation_state_loaded_version": conversation_state_loaded_version,
        "tone_repeat_hit": int(debug.get("tone_repeat_hit", 0) or 0),
        "tone_filler_stripped": int(debug.get("tone_filler_stripped", 0) or 0),
        "external_call_count": int(debug.get("external_call_count", 0) or 0),
        "llm_call_count": int(
            debug.get("llm_call_count", getattr(meta, "llm_calls", 0) if meta is not None else 0) or 0
        ),
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
    conversation_state_enabled = 0
    conversation_state_written = 0
    conversation_state_filter_merge_applied = 0
    conversation_state_loaded_versions: Dict[str, int] = {}
    totals_by_grounding_status: Dict[str, int] = {}
    totals_by_grounding_action: Dict[str, int] = {}
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
        grounding_status = str(metrics.get("grounding_status") or "").strip()
        if grounding_status:
            totals_by_grounding_status[grounding_status] = totals_by_grounding_status.get(grounding_status, 0) + 1
        grounding_action = str(metrics.get("grounding_safe_action") or "").strip()
        if grounding_action:
            totals_by_grounding_action[grounding_action] = totals_by_grounding_action.get(grounding_action, 0) + 1
        if bool(metrics.get("action_completed", False)):
            action_completed += 1
        if bool(metrics.get("conversation_state_enabled", False)):
            conversation_state_enabled += 1
        if bool(metrics.get("conversation_state_written", False)):
            conversation_state_written += 1
        if bool(metrics.get("conversation_state_filter_merge_applied", False)):
            conversation_state_filter_merge_applied += 1
        try:
            loaded_version = int(metrics.get("conversation_state_loaded_version", 0) or 0)
        except Exception:
            loaded_version = 0
        if loaded_version > 0:
            key = str(loaded_version)
            conversation_state_loaded_versions[key] = conversation_state_loaded_versions.get(key, 0) + 1
        tone_repeat_hits += int(metrics.get("tone_repeat_hit", 0) or 0)
        tone_filler_stripped += int(metrics.get("tone_filler_stripped", 0) or 0)

    return {
        "total_rows": total_rows,
        "by_status": dict(sorted(totals_by_status.items())),
        "by_workflow": dict(sorted(totals_by_workflow.items())),
        "by_action_kind": dict(sorted(totals_by_action.items())),
        "by_grounding_status": dict(sorted(totals_by_grounding_status.items())),
        "by_grounding_safe_action": dict(sorted(totals_by_grounding_action.items())),
        "action_completed": action_completed,
        "conversation_state_enabled": conversation_state_enabled,
        "conversation_state_written": conversation_state_written,
        "conversation_state_filter_merge_applied": conversation_state_filter_merge_applied,
        "conversation_state_loaded_versions": dict(sorted(conversation_state_loaded_versions.items())),
        "tone_repeat_hit": tone_repeat_hits,
        "tone_filler_stripped": tone_filler_stripped,
    }
