from typing import Any, Dict


def knowledge_degrade_reason(*, knowledge_error_message: str, knowledge_is_high_risk: bool, knowledge_sources_weak: bool) -> str:
    if knowledge_error_message and knowledge_is_high_risk:
        return "knowledge_unavailable"
    if knowledge_sources_weak and knowledge_is_high_risk:
        return "knowledge_needs_clarification"
    if knowledge_error_message:
        return "knowledge_unavailable"
    return ""


def knowledge_degrade_mode(*, degrade_reason: str) -> str:
    if degrade_reason in {"knowledge_unavailable", "knowledge_needs_clarification"}:
        return "clarify"
    return "answer"


def agentic_failure_reason(*, fallback_reason: str, existing_failure_reason: str = "") -> str:
    failure_reason = str(existing_failure_reason or "").strip()
    if failure_reason:
        return failure_reason
    clean_reason = str(fallback_reason or "").strip() or "empty_result"
    if clean_reason == "agentic_error":
        return "agentic_failed:agentic_error"
    return f"agentic_failed:{clean_reason}"


def runtime_failure_reason(*, error: Exception) -> str:
    return f"runtime_failed:{type(error).__name__}"


def build_fallback_debug(
    *,
    fallback_reason: str,
    failure_reason: str,
    outcome: str,
    used_tools: bool,
    trace: list[Dict[str, Any]],
    final_reply_present: bool,
) -> Dict[str, Any]:
    return {
        "fallback_to_component": True,
        "outcome": outcome,
        "used_tools": used_tools,
        "trace": trace,
        "fallback_reason": fallback_reason,
        "failure_reason": failure_reason,
        "final_reply_present": final_reply_present,
    }
