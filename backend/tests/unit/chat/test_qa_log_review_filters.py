from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.routes.training import (
    build_agentic_issue_clause,
    build_harness_tool_clause,
    build_review_status_clause,
)
from app.models.qa_log import QALog


def _compile_review_query(review_status: str) -> str:
    clause = build_review_status_clause(review_status)
    query = select(QALog).where(clause)
    return str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_failed_review_status_targets_failed_logs_only() -> None:
    sql = _compile_review_query("failed")

    assert "qa_logs.status =" in sql
    assert "failure_bucket" not in sql
    assert "grounding_status" not in sql


def test_passed_review_status_excludes_failure_and_grounding_issues() -> None:
    sql = _compile_review_query("passed")

    assert "qa_logs.status =" in sql
    assert "failure_bucket" in sql
    assert "grounding_status" in sql
    assert "agentic_expected_tool_missing" in sql
    assert "agentic_grounding_failed" in sql
    assert "agentic_fallback_to_component" in sql
    assert "other" in sql
    assert "grounded" in sql


def test_needs_review_status_captures_flagged_non_failed_logs() -> None:
    sql = _compile_review_query("needs_review")

    assert "qa_logs.status !=" in sql
    assert "IN ('NO_ANSWER', 'FALLBACK')" in sql or "IN ('no_answer', 'fallback')" in sql
    assert "failure_bucket" in sql
    assert "grounding_status" in sql
    assert "agentic_expected_tool_missing" in sql
    assert "agentic_grounding_failed" in sql
    assert "agentic_fallback_to_component" in sql


def test_agentic_expected_tool_missing_filter_targets_rollout_issue() -> None:
    clause = build_agentic_issue_clause("expected-tool-missing")
    query = select(QALog).where(clause)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "agentic_expected_tool_missing" in sql
    assert "agentic_fallback_reason" in sql
    assert "harness_fallback_reason" in sql


def test_agentic_grounding_failed_filter_targets_rollout_issue() -> None:
    clause = build_agentic_issue_clause("grounding_failed")
    query = select(QALog).where(clause)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "agentic_grounding_failed" in sql
    assert "harness_fallback_reason" in sql


def test_harness_tool_filter_targets_tools_called_array() -> None:
    clause = build_harness_tool_clause("search_products")
    query = select(QALog).where(clause)
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "@>" in sql
    assert "harness_tools_called" in list(compiled.params.values())


def test_invalid_review_status_raises_http_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        build_review_status_clause("review")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid reviewStatus. Expected one of: passed, needs_review, failed."


def test_invalid_agentic_issue_raises_http_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        build_agentic_issue_clause("maybe")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == (
        "Invalid agenticIssue. Expected one of: "
        "expected_tool_missing, grounding_failed, fallback_to_component, tool_first_selected."
    )
