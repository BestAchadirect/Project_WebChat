from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.core.config import settings


def feature_flags_snapshot() -> Dict[str, Any]:
    return {
        "chat_semantic_first_enabled": bool(getattr(settings, "CHAT_SEMANTIC_FIRST_ENABLED", True)),
        "chat_semantic_min_acceptance_score": float(
            getattr(settings, "CHAT_SEMANTIC_MIN_ACCEPTANCE_SCORE", 0.35)
        ),
        "chat_projection_read_enabled": bool(getattr(settings, "CHAT_PROJECTION_READ_ENABLED", False)),
        "chat_projection_dual_write_enabled": bool(getattr(settings, "CHAT_PROJECTION_DUAL_WRITE_ENABLED", True)),
        "chat_structured_query_cache_enabled": bool(
            getattr(settings, "CHAT_STRUCTURED_QUERY_CACHE_ENABLED", True)
        ),
        "chat_external_call_budget": int(getattr(settings, "CHAT_EXTERNAL_CALL_BUDGET", 3)),
        "chat_external_call_retry_max": int(getattr(settings, "CHAT_EXTERNAL_CALL_RETRY_MAX", 1)),
        "chat_external_call_fail_fast_seconds": float(
            getattr(settings, "CHAT_EXTERNAL_CALL_FAIL_FAST_SECONDS", 3.5)
        ),
        "chat_vector_top_k": int(getattr(settings, "CHAT_VECTOR_TOP_K", 12)),
        "chat_cross_sell_mode": str(getattr(settings, "CHAT_CROSS_SELL_MODE", "off")),
        "chat_max_history_tokens": int(getattr(settings, "CHAT_MAX_HISTORY_TOKENS", 1200)),
        "chat_hard_max_llm_calls_per_request": int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0)),
        "chat_hard_max_embeddings_per_request": int(
            getattr(settings, "CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST", 1)
        ),
        "chat_strict_retrieval_separation_enabled": bool(
            getattr(settings, "CHAT_STRICT_RETRIEVAL_SEPARATION_ENABLED", False)
        ),
        "chat_component_buckets_enabled": bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False)),
        "chat_component_buckets_shadow_mode": bool(
            getattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
        ),
        "chat_component_buckets_require_components": bool(
            getattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
        ),
        "chat_component_buckets_enabled_channels": str(
            getattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED_CHANNELS", "widget")
        ),
        "chat_conversation_state_enabled": bool(
            getattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False)
        ),
        "chat_challenge_context_enabled": bool(
            getattr(settings, "CHAT_CHALLENGE_CONTEXT_ENABLED", False)
        ),
        "chat_challenge_context_channels": str(
            getattr(settings, "CHAT_CHALLENGE_CONTEXT_CHANNELS", "widget,qa_console")
        ),
        "chat_tone_humanizer_enabled": bool(
            getattr(settings, "CHAT_TONE_HUMANIZER_ENABLED", True)
        ),
        "chat_tone_anti_repeat_window": int(
            getattr(settings, "CHAT_TONE_ANTI_REPEAT_WINDOW", 4)
        ),
        "chat_tone_max_sentences": int(getattr(settings, "CHAT_TONE_MAX_SENTENCES", 2)),
        "chat_tone_max_chars": int(getattr(settings, "CHAT_TONE_MAX_CHARS", 220)),
        "chat_tone_enabled_channels": str(getattr(settings, "CHAT_TONE_ENABLED_CHANNELS", "widget")),
        "chat_redis_cache_enabled": bool(getattr(settings, "CHAT_REDIS_CACHE_ENABLED", False)),
        "chat_catalog_version": str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
        "chat_prompt_version": str(getattr(settings, "CHAT_PROMPT_VERSION", "v1")),
        "chat_llm_routing_enabled": bool(getattr(settings, "CHAT_LLM_ROUTING_ENABLED", False)),
        "chat_llm_routing_model": str(getattr(settings, "CHAT_LLM_ROUTING_MODEL", "")),
        "chat_llm_routing_max_tokens": int(getattr(settings, "CHAT_LLM_ROUTING_MAX_TOKENS", 180)),
        "chat_llm_routing_timeout_ms": int(getattr(settings, "CHAT_LLM_ROUTING_TIMEOUT_MS", 3500)),
        "chat_llm_routing_timeout_retry_enabled": bool(
            getattr(settings, "CHAT_LLM_ROUTING_TIMEOUT_RETRY_ENABLED", True)
        ),
        "chat_llm_routing_timeout_retry_ms": int(
            getattr(settings, "CHAT_LLM_ROUTING_TIMEOUT_RETRY_MS", 2000)
        ),
        "chat_llm_routing_min_confidence": float(
            getattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)
        ),
        "chat_llm_routing_shadow_mode": bool(getattr(settings, "CHAT_LLM_ROUTING_SHADOW_MODE", False)),
        "chat_agentic_min_confidence": float(getattr(settings, "CHAT_AGENTIC_MIN_CONFIDENCE", 0.8)),
        "chat_clarify_guardrails_enabled": bool(
            getattr(settings, "CHAT_CLARIFY_GUARDRAILS_ENABLED", True)
        ),
        "chat_knowledge_min_relevance": float(getattr(settings, "CHAT_KNOWLEDGE_MIN_RELEVANCE", 0.55)),
        "chat_conversion_follow_ups_enabled": bool(
            getattr(settings, "CHAT_CONVERSION_FOLLOW_UPS_ENABLED", True)
        ),
        "chat_product_click_tracking_enabled": bool(
            getattr(settings, "CHAT_PRODUCT_CLICK_TRACKING_ENABLED", True)
        ),
        "openai_timeout_seconds": float(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 12.0)),
        "openai_max_retries": int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
    }


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
        "projection_lookup_ms": 0.0,
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
