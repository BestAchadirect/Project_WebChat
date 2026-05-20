from __future__ import annotations

import pytest

from app.services.chat.observability import accuracy_eval
from app.services.chat.observability.capture_eval import (
    build_chat_request_from_case,
    build_harness_trace_snapshot,
    filter_capture_cases,
)


def test_filter_capture_cases_only_keeps_response_contract_cases() -> None:
    cases = accuracy_eval.load_accuracy_cases(suite="all")

    filtered = filter_capture_cases(cases)

    assert filtered
    assert {str(case["kind"]) for case in filtered} == {"response_contract"}
    assert {str(case["suite"]) for case in filtered} == {"response"}


def test_build_chat_request_from_case_uses_dataset_inputs() -> None:
    case = accuracy_eval.load_accuracy_cases(suite="response")[0]

    request = build_chat_request_from_case(case)

    assert request.message == case["inputs"]["message"]
    assert request.locale == case["inputs"]["locale"]
    assert request.user_id == f"accuracy-{case['id']}"


def test_build_chat_request_from_case_requires_message() -> None:
    with pytest.raises(ValueError, match="missing inputs.message"):
        build_chat_request_from_case({"id": "missing-message", "inputs": {"locale": "en-US"}})


def test_build_harness_trace_snapshot_compacts_debug_trace() -> None:
    snapshot = build_harness_trace_snapshot(
        {
            "debug": {
                "harness_trace": {
                    "run_id": "chat-123",
                    "user_message": "do not copy full message",
                    "route": "catalog",
                    "workflow": "product_detail",
                    "execution_mode": "agentic",
                    "tools_called": ["check_inventory_db"],
                    "retrieved_products": 1,
                    "retrieved_sources": 0,
                    "fallback_used": False,
                    "timings_ms": {"prepare_context": 1.0, "finalize": 2.0},
                    "errors": ["tool failed"],
                    "warnings": ["weak grounding"],
                    "metadata": {
                        "large": "debug payload",
                        "tool_events": [{"tool": "check_inventory_db", "status": "ok"}],
                    },
                }
            }
        }
    )

    assert snapshot["run_id"] == "chat-123"
    assert snapshot["route"] == "catalog"
    assert snapshot["workflow"] == "product_detail"
    assert snapshot["execution_mode"] == "agentic"
    assert snapshot["tools_called"] == ["check_inventory_db"]
    assert snapshot["tool_count"] == 1
    assert snapshot["tool_event_count"] == 1
    assert snapshot["error_count"] == 1
    assert snapshot["warning_count"] == 1
    assert snapshot["retrieved_products"] == 1
    assert snapshot["timing_steps"] == ["finalize", "prepare_context"]
    assert "user_message" not in snapshot
    assert "metadata" not in snapshot


def test_build_harness_trace_snapshot_returns_empty_without_trace() -> None:
    assert build_harness_trace_snapshot({"debug": {"workflow": "catalog"}}) == {}
