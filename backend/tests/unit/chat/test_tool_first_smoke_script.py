from __future__ import annotations

from types import SimpleNamespace

from scripts.smoke_tool_first_chat import (
    SmokeCase,
    SmokeResult,
    ToolEvent,
    load_cases,
    result_issues,
    rollout_minimum_selected,
    summarize_response,
)


def test_load_cases_can_filter_by_case_id() -> None:
    cases = load_cases({"return_policy"})

    assert [case.id for case in cases] == ["return_policy"]
    assert cases[0].expected_workflow == "knowledge"
    assert cases[0].expected_tool == "search_knowledge_base"


def test_summarize_response_marks_tool_first_success() -> None:
    case = SmokeCase(
        id="return_policy",
        message="What is your return policy?",
        expected_workflow="knowledge",
        expected_tool="search_knowledge_base",
    )
    response = SimpleNamespace(
        debug={
            "workflow": "knowledge",
            "workflow_path": "agentic_primary",
            "agentic": {
                "selected": True,
                "trace": [
                    {
                        "tool": "search_knowledge_base",
                        "tool_status": "ok",
                        "result_count": 3,
                        "args": {"query": "return policy"},
                    }
                ],
                "grounding": {
                    "knowledge": {
                        "status": "grounded",
                        "safe_customer_action": "answer",
                    }
                },
            },
        },
        routing=SimpleNamespace(workflow="knowledge"),
        product_carousel=[],
        sources=[object(), object(), object()],
        qa_log_id="qa-1",
        conversation_id=123,
    )

    result = summarize_response(
        channel="widget",
        case=case,
        response=response,
        latency_ms=12.345,
    )

    assert result.passed is True
    assert result.workflow == "knowledge"
    assert result.workflow_path == "agentic_primary"
    assert result.source_count == 3
    assert result.tools[0].tool == "search_knowledge_base"
    assert result.issues == []


def test_result_issues_reports_missing_tool_and_grounding() -> None:
    issues = result_issues(
        expected_workflow="catalog",
        expected_tool="search_products",
        workflow="knowledge",
        agentic_selected=False,
        fallback_reason="agentic_grounding_failed",
        grounding_status="weak",
        tools=[ToolEvent(tool="search_knowledge_base", status="ok", result_count=2, args={})],
    )

    assert issues == [
        "workflow_mismatch:catalog->knowledge",
        "agentic_not_selected",
        "fallback:agentic_grounding_failed",
        "expected_tool_missing:search_products",
        "grounding_not_grounded:weak",
    ]


def test_rollout_minimum_selected_uses_per_channel_count() -> None:
    results = [
        SmokeResult(
            channel="widget",
            case_id=f"w-{index}",
            message="",
            workflow="catalog",
            workflow_path="agentic_primary",
            agentic_selected=True,
            fallback_reason="",
            grounding_status="grounded",
            grounding_action="show_cards",
            product_count=1,
            source_count=0,
            tools=[],
            issues=[],
            qa_log_id="",
            conversation_id="",
            latency_ms=1.0,
        )
        for index in range(4)
    ]
    results.extend(
        SmokeResult(
            channel="qa_console",
            case_id=f"q-{index}",
            message="",
            workflow="catalog",
            workflow_path="agentic_primary",
            agentic_selected=True,
            fallback_reason="",
            grounding_status="grounded",
            grounding_action="show_cards",
            product_count=1,
            source_count=0,
            tools=[],
            issues=[],
            qa_log_id="",
            conversation_id="",
            latency_ms=1.0,
        )
        for index in range(3)
    )

    assert rollout_minimum_selected(results) == 3
