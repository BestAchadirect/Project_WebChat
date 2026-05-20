from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.services.chat.observability import runtime_metrics
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities


def test_feature_flags_snapshot_does_not_expose_projection_read_flag() -> None:
    flags = runtime_metrics.feature_flags_snapshot()
    assert "chat_projection_read_enabled" not in flags


def test_feature_flags_snapshot_uses_shared_capability_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CACHE_LOG_INTERVAL_SECONDS", 17, raising=False)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_TEMPERATURE", 0.25, raising=False)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget, admin", raising=False)

    flags = runtime_metrics.feature_flags_snapshot()
    capabilities = build_chat_runtime_capabilities()

    assert flags["chat_cache_log_interval_seconds"] == 17
    assert flags["chat_llm_routing_temperature"] == 0.25
    assert flags["chat_cache_log_interval_seconds"] == capabilities.chat_cache_log_interval_seconds
    assert flags["chat_llm_routing_temperature"] == capabilities.chat_llm_routing_temperature


def test_new_latency_spans_contains_expected_defaults() -> None:
    spans = runtime_metrics.new_latency_spans()
    assert spans["total_ms"] == 0.0
    assert spans["llm_calls_count"] == 0
    assert spans["detail_mode_triggered"] is False


def test_add_latency_span_accumulates_and_clamps_negative_values() -> None:
    spans = runtime_metrics.new_latency_spans()
    runtime_metrics.add_latency_span(spans, "db_product_lookup_ms", 12.5)
    runtime_metrics.add_latency_span(spans, "db_product_lookup_ms", -5.0)
    runtime_metrics.add_latency_span(spans, "db_product_lookup_ms", 1.5)
    assert spans["db_product_lookup_ms"] == 14.0


def test_trim_history_for_llm_applies_token_cap() -> None:
    history = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
    ]
    trimmed = runtime_metrics.trim_history_for_llm(history=history, max_tokens=10)
    assert len(trimmed) <= len(history)
    assert all("content" in row for row in trimmed)


def test_build_latency_payload_counts_only_textual_llm_calls() -> None:
    spans = runtime_metrics.new_latency_spans()
    started = time.perf_counter() - 0.05
    token_usage = {
        "by_call": [
            {"kind": "embedding"},
            {"kind": "nlu"},
            {"kind": "llm_answer"},
        ]
    }
    payload = runtime_metrics.build_latency_payload(
        spans=spans,
        total_started=started,
        detail_mode_triggered=True,
        token_usage=token_usage,
    )
    assert payload["detail_mode_triggered"] is True
    assert payload["llm_calls_count"] == 2
    assert payload["total_ms"] > 0


def test_routing_snapshot_captures_decision_details() -> None:
    route_decision = SimpleNamespace(
        workflow="catalog",
        confidence=0.91,
        needs_products=True,
        needs_knowledge=False,
        needs_clarification=False,
        store_overview_request=False,
    )
    execution_decision = SimpleNamespace(
        execution_mode="component",
        selection_source="llm_retry",
        reason="selected",
        llm_reason="mixed request",
        llm_confidence=0.91,
        llm_workflow="catalog",
        llm_execution_mode="component",
        route_supported=True,
        tool_first_candidate=True,
        selection_blockers=("feature_disabled",),
        confidence_gate_applied=False,
        timeout_retry_used=True,
    )

    snapshot = runtime_metrics.routing_snapshot(
        route_decision=route_decision,
        execution_decision=execution_decision,
    )
    assert snapshot["workflow"] == "catalog"
    assert snapshot["selection_source"] == "llm_retry"
    assert snapshot["agentic_route_supported"] is True
    assert snapshot["agentic_tool_first_candidate"] is True
    assert snapshot["agentic_selection_blockers"] == ["feature_disabled"]
    assert snapshot["timeout_retry_used"] is True


def test_routing_snapshot_captures_agentic_guardrail_block() -> None:
    route_decision = SimpleNamespace(
        workflow="catalog",
        confidence=0.94,
        needs_products=True,
        needs_knowledge=False,
        needs_clarification=False,
        store_overview_request=False,
    )
    execution_decision = SimpleNamespace(
        execution_mode="component",
        selection_source="llm_guardrail",
        reason="feature_disabled",
        llm_reason="agentic route requested",
        llm_confidence=0.94,
        llm_workflow="catalog",
        llm_execution_mode="agentic",
        route_supported=True,
        tool_first_candidate=True,
        selection_blockers=("feature_disabled",),
        confidence_gate_applied=False,
        timeout_retry_used=False,
    )

    snapshot = runtime_metrics.routing_snapshot(
        route_decision=route_decision,
        execution_decision=execution_decision,
    )
    assert snapshot["workflow"] == "catalog"
    assert snapshot["execution_mode"] == "component"
    assert snapshot["selection_source"] == "llm_guardrail"
    assert snapshot["llm_execution_mode"] == "agentic"
    assert snapshot["agentic_route_supported"] is True
    assert snapshot["agentic_tool_first_candidate"] is True
    assert snapshot["agentic_selection_blockers"] == ["feature_disabled"]


def test_routing_snapshot_captures_timeout_guardrail_catalog() -> None:
    route_decision = SimpleNamespace(
        workflow="catalog",
        confidence=0.51,
        needs_products=True,
        needs_knowledge=False,
        needs_clarification=False,
        store_overview_request=False,
    )
    execution_decision = SimpleNamespace(
        execution_mode="component",
        selection_source="llm_timeout_guardrail",
        reason="routing_timeout_guardrail",
        llm_reason="error:TimeoutError",
        llm_confidence=0.0,
        llm_workflow="",
        llm_execution_mode="",
        confidence_gate_applied=False,
        timeout_retry_used=True,
    )

    snapshot = runtime_metrics.routing_snapshot(
        route_decision=route_decision,
        execution_decision=execution_decision,
    )
    assert snapshot["workflow"] == "catalog"
    assert snapshot["selection_source"] == "llm_timeout_guardrail"
    assert snapshot["timeout_retry_used"] is True
