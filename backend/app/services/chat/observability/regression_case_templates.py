from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Dict, List

from app.services.chat.observability.qa_metrics import extract_chat_metrics


_DATASET_TARGETS = {
    "coverage": "backend/tests/regression/data/chat_customer_message_coverage_cases.json",
    "response": "backend/tests/regression/data/chat_response_contract_cases.json",
}


def _slugify(value: str, *, max_parts: int = 8) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    parts = [part for part in cleaned.split("_") if part]
    if not parts:
        return "case"
    return "_".join(parts[:max_parts])


def _failure_bucket(metrics: Mapping[str, Any]) -> str:
    analysis = metrics.get("failure_analysis")
    if isinstance(analysis, Mapping):
        value = str(analysis.get("bucket") or "").strip().lower()
        if value:
            return value
    return str(metrics.get("failure_bucket") or "other").strip().lower() or "other"


def _failure_reason(metrics: Mapping[str, Any]) -> str:
    analysis = metrics.get("failure_analysis")
    if isinstance(analysis, Mapping):
        value = str(analysis.get("reason") or "").strip()
        if value:
            return value
    return str(metrics.get("failure_reason") or "").strip()


def _failure_action(metrics: Mapping[str, Any]) -> str:
    analysis = metrics.get("failure_analysis")
    if isinstance(analysis, Mapping):
        value = str(analysis.get("suggested_action") or "").strip()
        if value:
            return value
    return str(metrics.get("failure_suggested_action") or "").strip()


def _recommended_targets(bucket: str) -> List[Dict[str, str]]:
    if bucket in {"mixed_intent_clarification", "routing_mismatch", "no_answer"}:
        return [
            {
                "dataset": _DATASET_TARGETS["coverage"],
                "reason": "Add the raw user message to coverage so routing stays visible in CI.",
            }
        ]
    if bucket in {
        "hard_constraint_no_match",
        "catalog_unrelated_match",
        "context_leak",
        "related_product_anchor_reuse",
        "clarification_loop",
    }:
        return [
            {
                "dataset": _DATASET_TARGETS["coverage"],
                "reason": "Capture the customer phrasing in the message coverage dataset.",
            },
            {
                "dataset": _DATASET_TARGETS["response"],
                "reason": "Promote this into a response contract once the expected grounded behavior is known.",
            },
        ]
    return [
        {
            "dataset": _DATASET_TARGETS["coverage"],
            "reason": "Track the message shape first, then decide whether it also needs a contract test.",
        }
    ]


def build_regression_review_bundle(
    *,
    qa_log_id: str,
    question: str,
    answer: str,
    status: str,
    sources: Sequence[Mapping[str, Any]] | None,
    chat_metrics: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    metrics = dict(chat_metrics or {})
    failure_bucket = _failure_bucket(metrics)
    slug = _slugify(question)
    case_id = f"qa_{failure_bucket}_{slug}"
    observed_workflow = str(metrics.get("workflow") or metrics.get("response_workflow") or "").strip()
    observed_grounding = str(metrics.get("grounding_status") or "").strip()
    observed_route = str(metrics.get("route") or "").strip()
    sources_payload = [dict(item or {}) for item in list(sources or []) if isinstance(item, Mapping)]
    failure_reason = _failure_reason(metrics)
    failure_action = _failure_action(metrics)

    notes = (
        f"Seeded from QA log {qa_log_id}. "
        f"Observed workflow={observed_workflow or 'unknown'}, "
        f"grounding={observed_grounding or 'unknown'}, "
        f"failure_bucket={failure_bucket or 'other'}."
    ).strip()

    coverage_case_template = {
        "review_required": True,
        "id": case_id,
        "group": "qa_log_failures",
        "message": str(question or ""),
        "expected_workflow": "__REVIEW_REQUIRED__",
        "notes": notes,
        "meta": {
            "qa_log_id": str(qa_log_id or ""),
            "conversation_id": metrics.get("conversation_id"),
            "observed_status": str(status or ""),
            "observed_workflow": observed_workflow,
            "observed_route": observed_route,
            "observed_grounding_status": observed_grounding,
            "failure_bucket": failure_bucket,
            "failure_reason": failure_reason,
            "failure_suggested_action": failure_action,
        },
    }

    response_contract_template = {
        "review_required": True,
        "id": f"{case_id}_response",
        "name": f"{case_id}_response",
        "suite": "response",
        "bucket": failure_bucket or "qa_log_failure",
        "kind": "response_contract",
        "fallback_actual_response": {
            "routing": {
                "workflow": observed_workflow,
            },
            "reply_text": str(answer or ""),
            "follow_up_questions": [],
            "sources": sources_payload,
            "product_carousel": [],
            "debug": {
                "conversation_id": metrics.get("conversation_id"),
                "route": observed_route,
                "grounding_status": observed_grounding,
                "grounding_safe_action": str(metrics.get("grounding_safe_action") or ""),
                "failure_bucket": failure_bucket,
            },
        },
        "expected_template": {
            "workflow": "__REVIEW_REQUIRED__",
            "reply_must_include": [],
            "reply_must_not_include": [],
            "follow_ups_include": [],
            "required_component_types": [],
            "product_count_min": "__REVIEW_REQUIRED__",
            "product_count_max": "__REVIEW_REQUIRED__",
            "source_count_min": "__REVIEW_REQUIRED__",
        },
        "notes": (
            f"{notes} QA logs do not store product cards or components, "
            "so this contract template must be completed by replaying the conversation or inspecting the linked conversation messages."
        ),
    }

    return {
        "qa_log_id": str(qa_log_id or ""),
        "conversation_id": metrics.get("conversation_id"),
        "question": str(question or ""),
        "answer": str(answer or ""),
        "status": str(status or ""),
        "observed": {
            "workflow": observed_workflow,
            "route": observed_route,
            "grounding_status": observed_grounding,
            "grounding_safe_action": str(metrics.get("grounding_safe_action") or ""),
            "product_count": int(metrics.get("product_count", 0) or 0),
            "source_count": int(metrics.get("source_count", 0) or 0),
            "failure_bucket": failure_bucket,
            "failure_reason": failure_reason,
            "failure_suggested_action": failure_action,
            "conversation_state_filter_merge_applied": bool(
                metrics.get("conversation_state_filter_merge_applied", False)
            ),
            "llm_call_count": int(metrics.get("llm_call_count", 0) or 0),
        },
        "recommended_targets": _recommended_targets(failure_bucket),
        "promotion_checklist": [
            "Review the observed workflow and replace every __REVIEW_REQUIRED__ placeholder.",
            "If the expected behavior depends on grounding, replay the turn and inspect the conversation messages before promoting a response contract.",
            "Add the approved case to the target regression dataset and run the regression suite before release.",
        ],
        "coverage_case_template": coverage_case_template,
        "response_contract_template": response_contract_template,
    }


def build_review_bundle_from_qa_log(qa_log: Any) -> Dict[str, Any]:
    metrics = extract_chat_metrics(getattr(qa_log, "token_usage", None))
    return build_regression_review_bundle(
        qa_log_id=str(getattr(qa_log, "id", "") or ""),
        question=str(getattr(qa_log, "question", "") or ""),
        answer=str(getattr(qa_log, "answer", "") or ""),
        status=str(getattr(qa_log, "status", "") or ""),
        sources=list(getattr(qa_log, "sources", []) or []),
        chat_metrics=metrics,
    )
