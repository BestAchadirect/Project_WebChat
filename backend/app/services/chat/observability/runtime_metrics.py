from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities


def feature_flags_snapshot() -> Dict[str, Any]:
    return build_chat_runtime_capabilities().to_dict()


def estimated_tokens(value: str) -> int:
    if not value:
        return 0
    return max(1, int(len(str(value)) / 4))


def trim_history_for_llm(history: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
    if not history:
        return []
    limit = max(32, int(max_tokens or 0))
    kept: List[Dict[str, Any]] = []
    consumed = 0
    for item in reversed(history):
        content = str(item.get("content") or "")
        token_cost = estimated_tokens(content) + 8
        if consumed + token_cost > limit:
            continue
        kept.append(item)
        consumed += token_cost
    kept.reverse()
    return kept


def new_latency_spans() -> Dict[str, Any]:
    return {
        "total_ms": 0.0,
        "workflow_routing_ms": 0.0,
        "detail_mode_triggered": False,
        "detail_query_parser_ms": 0.0,
        "retrieval_gate_ms": 0.0,
        "vector_search_ms": 0.0,
        "db_product_lookup_ms": 0.0,
        "tickets_service_ms": 0.0,
        "llm_calls_count": 0,
        "llm_parse_ms": 0.0,
        "llm_answer_ms": 0.0,
        "response_build_ms": 0.0,
    }


def add_latency_span(spans: Dict[str, Any], key: str, elapsed_ms: float) -> None:
    current = float(spans.get(key, 0.0) or 0.0)
    spans[key] = current + max(0.0, float(elapsed_ms))


def merge_catalog_metrics_into_spans(*, spans: Dict[str, Any], catalog_search: Any) -> None:
    metrics = getattr(catalog_search, "last_metrics", {}) or {}
    vector_ms = float(metrics.get("vector_search_ms", 0.0) or 0.0)
    db_ms = float(metrics.get("db_product_lookup_ms", 0.0) or 0.0)
    add_latency_span(spans, "vector_search_ms", vector_ms)
    add_latency_span(spans, "db_product_lookup_ms", db_ms)


def routing_snapshot(*, route_decision: Any, execution_decision: Any) -> Dict[str, Any]:
    route = getattr(route_decision, "workflow", "")
    return {
        "workflow": str(route or ""),
        "execution_mode": str(getattr(execution_decision, "execution_mode", "") or ""),
        "selection_source": str(getattr(execution_decision, "selection_source", "") or ""),
        "reason": str(getattr(execution_decision, "reason", "") or ""),
        "confidence": round(float(getattr(route_decision, "confidence", 0.0) or 0.0), 3),
        "needs_products": bool(getattr(route_decision, "needs_products", False)),
        "needs_knowledge": bool(getattr(route_decision, "needs_knowledge", False)),
        "needs_clarification": bool(getattr(route_decision, "needs_clarification", False)),
        "store_overview_request": bool(getattr(route_decision, "store_overview_request", False)),
        "recommendation_mode_requested": str(
            getattr(route_decision, "recommendation_mode_requested", "") or ""
        ),
        "llm_reason": str(getattr(execution_decision, "llm_reason", "") or ""),
        "llm_confidence": round(float(getattr(execution_decision, "llm_confidence", 0.0) or 0.0), 3),
        "llm_workflow": str(getattr(execution_decision, "llm_workflow", "") or ""),
        "llm_execution_mode": str(getattr(execution_decision, "llm_execution_mode", "") or ""),
        "confidence_gate_applied": bool(getattr(execution_decision, "confidence_gate_applied", False)),
        "timeout_retry_used": bool(getattr(execution_decision, "timeout_retry_used", False)),
    }


def build_latency_payload(
    *,
    spans: Dict[str, Any],
    total_started: float,
    detail_mode_triggered: bool,
    token_usage: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = dict(spans or {})
    payload["total_ms"] = (time.perf_counter() - total_started) * 1000.0
    payload["detail_mode_triggered"] = bool(detail_mode_triggered)
    by_call = []
    if isinstance(token_usage, dict):
        raw_calls = token_usage.get("by_call")
        if isinstance(raw_calls, list):
            by_call = raw_calls
    llm_textual_calls = 0
    for call in by_call:
        kind = str((call or {}).get("kind", "")).strip().lower()
        if kind.startswith("embedding"):
            continue
        llm_textual_calls += 1
    payload["llm_calls_count"] = int(llm_textual_calls)

    rounded: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            rounded[key] = value
        elif isinstance(value, (int, float)):
            if key == "llm_calls_count":
                rounded[key] = int(value)
            else:
                rounded[key] = round(float(value), 2)
        else:
            rounded[key] = value
    return rounded
