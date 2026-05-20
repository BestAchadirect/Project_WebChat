from __future__ import annotations

import pytest

pytest.importorskip("pydantic_settings")

from app.api.deps import get_db
from app.api.routes.training import qa_router


async def override_get_db():
    return object()


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _ExecuteRows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarRows(self._rows)


class _RolloutSummaryDB:
    async def execute(self, _query):
        return _ExecuteRows(
            [
                {
                    "chat_metrics": {
                        "status": "success",
                        "workflow": "catalog",
                        "tool_first_selected": True,
                        "agentic_fallback_to_component": False,
                        "agentic_expected_tool_missing": False,
                        "agentic_grounding_failed": False,
                        "harness_route": "catalog",
                        "harness_workflow": "catalog_search",
                        "harness_tools_called": ["search_products"],
                        "harness_tool_count": 1,
                        "failure_bucket": "other",
                    }
                },
                {
                    "chat_metrics": {
                        "status": "fallback",
                        "workflow": "knowledge",
                        "tool_first_selected": True,
                        "agentic_fallback_to_component": True,
                        "agentic_expected_tool_missing": True,
                        "agentic_grounding_failed": False,
                        "agentic_fallback_reason": "agentic_expected_tool_missing",
                        "agentic_missing_expected_tools": ["search_knowledge_base"],
                        "harness_route": "knowledge",
                        "harness_workflow": "policy_info",
                        "harness_tools_called": [],
                        "failure_bucket": "agentic_expected_tool_missing",
                    }
                },
                {
                    "chat_metrics": {
                        "status": "fallback",
                        "workflow": "catalog",
                        "tool_first_selected": True,
                        "agentic_fallback_to_component": True,
                        "agentic_expected_tool_missing": False,
                        "agentic_grounding_failed": True,
                        "agentic_fallback_reason": "agentic_grounding_failed",
                        "harness_route": "catalog",
                        "harness_workflow": "catalog_search",
                        "harness_tools_called": ["search_products"],
                        "harness_tool_count": 1,
                        "failure_bucket": "agentic_grounding_failed",
                    }
                },
            ]
        )


async def override_rollout_summary_db():
    return _RolloutSummaryDB()


def test_qa_logs_reject_invalid_review_status(build_client) -> None:
    client = build_client(
        router=qa_router,
        prefix="/dashboard/qa",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.get("/dashboard/qa/qa-logs", params={"reviewStatus": "maybe"})

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Invalid reviewStatus. Expected one of: passed, needs_review, failed."
    }


def test_qa_logs_reject_invalid_agentic_issue(build_client) -> None:
    client = build_client(
        router=qa_router,
        prefix="/dashboard/qa",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.get("/dashboard/qa/qa-logs", params={"agenticIssue": "maybe"})

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "Invalid agenticIssue. Expected one of: "
            "expected_tool_missing, grounding_failed, fallback_to_component, tool_first_selected."
        )
    }


def test_qa_rollout_summary_rejects_invalid_agentic_issue(build_client) -> None:
    client = build_client(
        router=qa_router,
        prefix="/dashboard/qa",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.get("/dashboard/qa/qa-logs/rollout-summary", params={"agenticIssue": "maybe"})

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "Invalid agenticIssue. Expected one of: "
            "expected_tool_missing, grounding_failed, fallback_to_component, tool_first_selected."
        )
    }


def test_qa_rollout_summary_returns_tool_first_counters(build_client) -> None:
    client = build_client(
        router=qa_router,
        prefix="/dashboard/qa",
        dependency_overrides={get_db: override_rollout_summary_db},
    )

    response = client.get(
        "/dashboard/qa/qa-logs/rollout-summary",
        params={"channel": "widget", "maxRows": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sampledRows"] == 3
    assert payload["maxRows"] == 10
    assert payload["filters"]["channel"] == "widget"

    tool_first = payload["toolFirst"]
    assert tool_first["total_rows"] == 3
    assert tool_first["tool_first_selected"] == 3
    assert tool_first["fallback_to_component"] == 2
    assert tool_first["expected_tool_missing"] == 1
    assert tool_first["grounding_failed"] == 1
    assert tool_first["top_tools"] == [{"tool": "search_products", "count": 2}]
    assert tool_first["by_agentic_fallback_reason"] == {
        "agentic_expected_tool_missing": 1,
        "agentic_grounding_failed": 1,
    }
    assert tool_first["by_agentic_missing_expected_tool"] == {
        "search_knowledge_base": 1,
    }


def test_qa_logs_reject_inverted_created_range(build_client) -> None:
    client = build_client(
        router=qa_router,
        prefix="/dashboard/qa",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.get(
        "/dashboard/qa/qa-logs",
        params={
            "createdFrom": "2026-05-19T12:00:00Z",
            "createdTo": "2026-05-18T12:00:00Z",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "createdTo must be greater than or equal to createdFrom."
    }


def test_qa_logs_reject_limit_offset_pagination(build_client) -> None:
    client = build_client(
        router=qa_router,
        prefix="/dashboard/qa",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.get("/dashboard/qa/qa-logs", params={"limit": 20, "offset": 0})

    assert response.status_code == 400
    assert response.json() == {
        "detail": "limit/offset pagination is no longer supported. Use page and pageSize."
    }
