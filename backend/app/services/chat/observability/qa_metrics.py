from typing import Any, Dict, Iterable, List, Optional

from app.schemas.chat import ChatResponse
import app.services.chat.presentation.component_contract as component_contract
from app.services.chat.observability.qa_failure_analysis import classify_failure


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _coerce_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _increment(counter: Dict[str, int], value: Any) -> None:
    key = _clean_text(value)
    if key:
        counter[key] = counter.get(key, 0) + 1


def _harness_trace_from_debug(debug: Dict[str, Any]) -> Dict[str, Any]:
    raw_trace = debug.get("harness_trace") if isinstance(debug, dict) else None
    return dict(raw_trace or {}) if isinstance(raw_trace, dict) else {}


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
    conversation_id: Optional[int],
    user_text: str,
    response: ChatResponse,
    channel: Optional[str],
) -> Dict[str, Any]:
    debug = dict(getattr(response, "debug", {}) or {})
    harness_trace = _harness_trace_from_debug(debug)
    harness_tools = [
        _clean_text(item)
        for item in _coerce_list(harness_trace.get("tools_called"))
        if _clean_text(item)
    ]
    harness_route = _clean_text(harness_trace.get("route"))
    harness_workflow = _clean_text(harness_trace.get("workflow"))
    harness_execution_mode = _clean_text(harness_trace.get("execution_mode"))
    harness_grounding_status = _clean_text(harness_trace.get("grounding_status"))
    harness_fallback_used = bool(harness_trace.get("fallback_used", False))
    harness_fallback_reason = _clean_text(harness_trace.get("fallback_reason"))
    harness_clarification_reason = _clean_text(harness_trace.get("clarification_reason"))
    harness_retrieved_products = _coerce_int(harness_trace.get("retrieved_products"))
    harness_retrieved_sources = _coerce_int(harness_trace.get("retrieved_sources"))
    retrieval_gate = debug.get("retrieval_gate") if isinstance(debug.get("retrieval_gate"), dict) else {}
    grounding = debug.get("grounding") if isinstance(debug.get("grounding"), dict) else {}
    knowledge_grounding = debug.get("knowledge_grounding") if isinstance(debug.get("knowledge_grounding"), dict) else {}
    latency = debug.get("latency_spans") if isinstance(debug.get("latency_spans"), dict) else {}
    agentic = debug.get("agentic") if isinstance(debug.get("agentic"), dict) else {}
    agentic_selected = bool(agentic.get("selected", False))
    agentic_fallback_to_component = bool(agentic.get("fallback_to_component", False))
    agentic_fallback_reason = _clean_text(agentic.get("fallback_reason"))
    agentic_grounding_failed = bool(
        agentic_fallback_reason == "agentic_grounding_failed"
        or harness_fallback_reason == "agentic_grounding_failed"
    )
    agentic_missing_expected_tools = [
        _clean_text(item)
        for item in _coerce_list(agentic.get("missing_expected_tools"))
        if _clean_text(item)
    ]
    agentic_expected_tool_missing = bool(
        agentic.get("expected_tool_missing", False)
        or agentic_fallback_reason == "agentic_expected_tool_missing"
        or harness_fallback_reason == "agentic_expected_tool_missing"
    )
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
    action_completed = bool(agentic.get("used_tools", False) or harness_tools)
    response_products = component_contract.product_cards_from_response(response)
    response_follow_ups = component_contract.follow_up_questions_from_response(response)
    grounding_status = str(
        grounding.get("status")
        or knowledge_grounding.get("status")
        or debug.get("grounding_status")
        or debug.get("knowledge_grounding_status")
        or harness_grounding_status
        or ""
    ).strip() or None
    grounding_safe_action = str(
        grounding.get("safe_customer_action")
        or knowledge_grounding.get("safe_customer_action")
        or debug.get("grounding_safe_action")
        or debug.get("knowledge_grounding_safe_action")
        or ""
    ).strip() or None
    failure_analysis = classify_failure(
        user_text=user_text,
        response=response,
        chat_metrics={
            "workflow": str(debug.get("workflow") or response_workflow or "").strip(),
            "response_workflow": response_workflow,
            "route": str(debug.get("workflow_path") or "").strip(),
            "status": normalized_status,
            "grounding_status": grounding_status,
            "grounding_safe_action": grounding_safe_action,
            "product_count": len(list(response_products or [])),
            "has_products": bool(response_products),
            "conversation_state_filter_merge_applied": conversation_state_filter_merge_applied,
            "harness_trace": harness_trace,
            "harness_route": harness_route or None,
            "harness_workflow": harness_workflow or None,
            "harness_execution_mode": harness_execution_mode or None,
            "harness_fallback_used": harness_fallback_used,
            "harness_fallback_reason": harness_fallback_reason or None,
            "harness_clarification_reason": harness_clarification_reason or None,
            "harness_retrieved_products": harness_retrieved_products,
            "harness_retrieved_sources": harness_retrieved_sources,
            "harness_tool_count": len(harness_tools),
            "agentic_selected": agentic_selected,
            "agentic_fallback_to_component": agentic_fallback_to_component,
            "agentic_fallback_reason": agentic_fallback_reason or None,
            "agentic_grounding_failed": agentic_grounding_failed,
            "agentic_expected_tool_missing": agentic_expected_tool_missing,
            "agentic_missing_expected_tools": list(agentic_missing_expected_tools),
        },
    )

    if action_completed:
        action_kind = "agentic_tools"

    failure_payload = failure_analysis.to_dict()

    metrics = {
        "conversation_id": int(conversation_id) if conversation_id is not None else None,
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
        "grounding_status": grounding_status,
        "grounding_safe_action": grounding_safe_action,
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
        "agentic_selected": agentic_selected,
        "tool_first_selected": agentic_selected,
        "agentic_fallback_to_component": agentic_fallback_to_component,
        "agentic_fallback_reason": agentic_fallback_reason or None,
        "agentic_grounding_failed": agentic_grounding_failed,
        "agentic_expected_tool_missing": agentic_expected_tool_missing,
        "agentic_expected_tools": [
            _clean_text(item)
            for item in _coerce_list(agentic.get("expected_tools"))
            if _clean_text(item)
        ],
        "agentic_actual_tools": [
            _clean_text(item)
            for item in _coerce_list(agentic.get("actual_tools"))
            if _clean_text(item)
        ],
        "agentic_missing_expected_tools": list(agentic_missing_expected_tools),
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
        "failure_bucket": failure_payload["bucket"],
        "failure_confidence": float(failure_payload["confidence"]),
        "failure_reason": failure_payload["reason"],
        "failure_suggested_action": failure_payload["suggested_action"],
        "failure_severity": failure_payload["severity"],
        "failure_signals": list(failure_payload["signals"]),
        "failure_analysis": failure_payload,
        "harness_trace_present": bool(harness_trace),
        "harness_run_id": _clean_text(harness_trace.get("run_id")) or None,
        "harness_route": harness_route or None,
        "harness_workflow": harness_workflow or None,
        "harness_execution_mode": harness_execution_mode or None,
        "harness_fallback_used": harness_fallback_used,
        "harness_fallback_reason": harness_fallback_reason or None,
        "harness_clarification_required": bool(harness_trace.get("clarification_required", False)),
        "harness_clarification_reason": harness_clarification_reason or None,
        "harness_grounding_status": harness_grounding_status or None,
        "harness_tool_count": len(harness_tools),
        "harness_tools_called": list(harness_tools),
        "harness_retrieved_products": harness_retrieved_products,
        "harness_retrieved_sources": harness_retrieved_sources,
    }
    return metrics


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
    totals_by_failure_bucket: Dict[str, int] = {}
    totals_by_harness_route: Dict[str, int] = {}
    totals_by_harness_workflow: Dict[str, int] = {}
    totals_by_harness_execution_mode: Dict[str, int] = {}
    totals_by_harness_grounding_status: Dict[str, int] = {}
    totals_by_harness_fallback_reason: Dict[str, int] = {}
    totals_by_harness_clarification_reason: Dict[str, int] = {}
    totals_by_harness_tool: Dict[str, int] = {}
    totals_by_agentic_fallback_reason: Dict[str, int] = {}
    totals_by_agentic_missing_expected_tool: Dict[str, int] = {}
    action_completed = 0
    harness_fallback_used = 0
    harness_clarification_required = 0
    harness_tool_calls = 0
    harness_retrieved_products = 0
    harness_retrieved_sources = 0
    tool_first_selected = 0
    agentic_fallback_to_component = 0
    agentic_grounding_failed = 0
    agentic_expected_tool_missing = 0
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
        failure_bucket = str(
            metrics.get("failure_bucket")
            or (metrics.get("failure_analysis") or {}).get("bucket")
            or ""
        ).strip()
        if failure_bucket:
            totals_by_failure_bucket[failure_bucket] = totals_by_failure_bucket.get(failure_bucket, 0) + 1
        _increment(totals_by_harness_route, metrics.get("harness_route"))
        _increment(totals_by_harness_workflow, metrics.get("harness_workflow"))
        _increment(totals_by_harness_execution_mode, metrics.get("harness_execution_mode"))
        _increment(totals_by_harness_grounding_status, metrics.get("harness_grounding_status"))
        _increment(totals_by_harness_fallback_reason, metrics.get("harness_fallback_reason"))
        _increment(totals_by_harness_clarification_reason, metrics.get("harness_clarification_reason"))
        _increment(totals_by_agentic_fallback_reason, metrics.get("agentic_fallback_reason"))
        for missing_tool in _coerce_list(metrics.get("agentic_missing_expected_tools")):
            _increment(totals_by_agentic_missing_expected_tool, missing_tool)
        for tool_name in _coerce_list(metrics.get("harness_tools_called")):
            _increment(totals_by_harness_tool, tool_name)
        if bool(metrics.get("action_completed", False)):
            action_completed += 1
        if bool(metrics.get("tool_first_selected", False) or metrics.get("agentic_selected", False)):
            tool_first_selected += 1
        if bool(metrics.get("agentic_fallback_to_component", False)):
            agentic_fallback_to_component += 1
        if bool(metrics.get("agentic_grounding_failed", False)):
            agentic_grounding_failed += 1
        if bool(metrics.get("agentic_expected_tool_missing", False)):
            agentic_expected_tool_missing += 1
        if bool(metrics.get("harness_fallback_used", False)):
            harness_fallback_used += 1
        if bool(metrics.get("harness_clarification_required", False)):
            harness_clarification_required += 1
        harness_tool_calls += int(metrics.get("harness_tool_count", 0) or 0)
        harness_retrieved_products += _coerce_int(metrics.get("harness_retrieved_products"))
        harness_retrieved_sources += _coerce_int(metrics.get("harness_retrieved_sources"))
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
        "by_failure_bucket": dict(sorted(totals_by_failure_bucket.items())),
        "by_harness_route": dict(sorted(totals_by_harness_route.items())),
        "by_harness_workflow": dict(sorted(totals_by_harness_workflow.items())),
        "by_harness_execution_mode": dict(sorted(totals_by_harness_execution_mode.items())),
        "by_harness_grounding_status": dict(sorted(totals_by_harness_grounding_status.items())),
        "by_harness_fallback_reason": dict(sorted(totals_by_harness_fallback_reason.items())),
        "by_harness_clarification_reason": dict(sorted(totals_by_harness_clarification_reason.items())),
        "by_harness_tool": dict(sorted(totals_by_harness_tool.items())),
        "by_agentic_fallback_reason": dict(sorted(totals_by_agentic_fallback_reason.items())),
        "by_agentic_missing_expected_tool": dict(sorted(totals_by_agentic_missing_expected_tool.items())),
        "top_harness_tools": [
            {"tool": tool, "count": count}
            for tool, count in sorted(
                totals_by_harness_tool.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ],
        "action_completed": action_completed,
        "tool_first_selected": tool_first_selected,
        "agentic_fallback_to_component": agentic_fallback_to_component,
        "agentic_grounding_failed": agentic_grounding_failed,
        "agentic_expected_tool_missing": agentic_expected_tool_missing,
        "harness_fallback_used": harness_fallback_used,
        "harness_clarification_required": harness_clarification_required,
        "harness_tool_calls": harness_tool_calls,
        "harness_retrieved_products": harness_retrieved_products,
        "harness_retrieved_sources": harness_retrieved_sources,
        "conversation_state_enabled": conversation_state_enabled,
        "conversation_state_written": conversation_state_written,
        "conversation_state_filter_merge_applied": conversation_state_filter_merge_applied,
        "conversation_state_loaded_versions": dict(sorted(conversation_state_loaded_versions.items())),
        "tone_repeat_hit": tone_repeat_hits,
        "tone_filler_stripped": tone_filler_stripped,
    }


def build_tool_first_rollout_summary(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    summary = summarize_chat_metrics(rows)
    total_rows = int(summary.get("total_rows", 0) or 0)
    selected = int(summary.get("tool_first_selected", 0) or 0)
    fallback_to_component = int(summary.get("agentic_fallback_to_component", 0) or 0)
    expected_tool_missing = int(summary.get("agentic_expected_tool_missing", 0) or 0)
    grounding_failed = int(summary.get("agentic_grounding_failed", 0) or 0)
    selected_denominator = max(1, selected)
    return {
        "total_rows": total_rows,
        "tool_first_selected": selected,
        "tool_first_selection_rate": round(selected / max(1, total_rows), 4),
        "fallback_to_component": fallback_to_component,
        "fallback_to_component_rate": round(fallback_to_component / selected_denominator, 4),
        "expected_tool_missing": expected_tool_missing,
        "expected_tool_missing_rate": round(expected_tool_missing / selected_denominator, 4),
        "grounding_failed": grounding_failed,
        "grounding_failed_rate": round(grounding_failed / selected_denominator, 4),
        "top_tools": list(summary.get("top_harness_tools") or []),
        "by_agentic_fallback_reason": dict(summary.get("by_agentic_fallback_reason") or {}),
        "by_agentic_missing_expected_tool": dict(summary.get("by_agentic_missing_expected_tool") or {}),
        "by_harness_route": dict(summary.get("by_harness_route") or {}),
        "by_harness_workflow": dict(summary.get("by_harness_workflow") or {}),
        "by_failure_bucket": dict(summary.get("by_failure_bucket") or {}),
        "raw_summary": summary,
    }
