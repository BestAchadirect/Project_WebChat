from __future__ import annotations

import time

import pytest

pytest.importorskip("pydantic_settings")

from app.services.chat.observability import runtime_metrics


def test_feature_flags_snapshot_does_not_expose_projection_read_flag() -> None:
    flags = runtime_metrics.feature_flags_snapshot()
    assert "chat_projection_read_enabled" not in flags


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
