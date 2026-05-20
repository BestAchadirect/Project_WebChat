from __future__ import annotations

from scripts.check_tool_first_rollout import (
    assess_tool_first_summary,
    exit_code_for_assessments,
)


def _payload(
    *,
    selected: int = 100,
    fallback_rate: float = 0.0,
    expected_tool_rate: float = 0.0,
    grounding_rate: float = 0.0,
    by_status: dict[str, int] | None = None,
) -> dict:
    return {
        "toolFirst": {
            "tool_first_selected": selected,
            "fallback_to_component_rate": fallback_rate,
            "expected_tool_missing_rate": expected_tool_rate,
            "grounding_failed_rate": grounding_rate,
            "top_tools": [{"tool": "search_products", "count": 12}],
            "raw_summary": {"by_status": by_status or {"success": selected}},
        }
    }


def test_assess_tool_first_summary_marks_green_under_thresholds() -> None:
    assessment = assess_tool_first_summary(
        "widget",
        _payload(
            selected=120,
            fallback_rate=0.05,
            expected_tool_rate=0.01,
            grounding_rate=0.01,
        ),
    )

    assert assessment.status == "green"
    assert assessment.reasons == []
    assert assessment.top_tools == [{"tool": "search_products", "count": 12}]


def test_assess_tool_first_summary_marks_yellow_at_warning_thresholds() -> None:
    assessment = assess_tool_first_summary(
        "widget",
        _payload(selected=120, fallback_rate=0.10, expected_tool_rate=0.02),
    )

    assert assessment.status == "yellow"
    assert any("fallback_to_component_rate" in reason for reason in assessment.reasons)
    assert any("expected_tool_missing_rate" in reason for reason in assessment.reasons)


def test_assess_tool_first_summary_marks_red_above_failure_thresholds() -> None:
    assessment = assess_tool_first_summary(
        "qa_console",
        _payload(selected=120, fallback_rate=0.21, grounding_rate=0.06),
    )

    assert assessment.status == "red"
    assert any("fallback_to_component_rate" in reason for reason in assessment.reasons)
    assert any("grounding_failed_rate" in reason for reason in assessment.reasons)


def test_assess_tool_first_summary_marks_red_for_failed_or_no_answer_rows() -> None:
    assessment = assess_tool_first_summary(
        "widget",
        _payload(selected=120, by_status={"success": 118, "failed": 1, "no_answer": 1}),
    )

    assert assessment.status == "red"
    assert assessment.failed_or_no_answer_rows == 2
    assert assessment.reasons == ["failed_or_no_answer_rows=2"]


def test_assess_tool_first_summary_marks_insufficient_sample() -> None:
    assessment = assess_tool_first_summary("widget", _payload(selected=25))

    assert assessment.status == "insufficient_sample"
    assert assessment.reasons == ["insufficient_sample: selected=25, minimum=100"]


def test_exit_code_for_assessments() -> None:
    green = assess_tool_first_summary("widget", _payload(selected=120))
    yellow = assess_tool_first_summary("qa_console", _payload(selected=120, fallback_rate=0.10))
    red = assess_tool_first_summary("widget", _payload(selected=120, fallback_rate=0.21))

    assert exit_code_for_assessments([green]) == 0
    assert exit_code_for_assessments([green, yellow]) == 2
    assert exit_code_for_assessments([green, yellow, red]) == 1
