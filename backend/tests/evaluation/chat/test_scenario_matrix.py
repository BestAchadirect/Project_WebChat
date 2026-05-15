from __future__ import annotations

import pytest

from tests.evaluation.chat.eval_harness import ChatEvalHarness, ChatEvalResult
from tests.evaluation.chat.scenario_loader import load_scenarios


pytestmark = pytest.mark.evaluation

CASES = load_scenarios("customer_scenarios.yaml")


def _assert_expected(result: ChatEvalResult, expected: dict[str, object]) -> None:
    if "internal_workflow" in expected:
        assert result.internal_workflow == expected["internal_workflow"]
    if "filters" in expected:
        for key, value in dict(expected["filters"] or {}).items():
            assert result.filters.get(str(key)) == value
    if "should_not_force_filters" in expected:
        for key in list(expected["should_not_force_filters"] or []):
            assert str(key) not in result.filters
    if "should_clarify" in expected:
        assert result.should_clarify is bool(expected["should_clarify"])
    if "pending_task_type" in expected:
        assert result.pending_task_type == expected["pending_task_type"]
    if "missing_slot" in expected:
        assert result.missing_slot == expected["missing_slot"]
    if "product_anchor" in expected:
        assert result.product_anchor == expected["product_anchor"]
    if "answer_must_include" in expected:
        answer_text = result.answer_text.lower()
        for token in list(expected["answer_must_include"] or []):
            assert str(token).lower() in answer_text
    if "answer_must_not_include" in expected:
        answer_text = result.answer_text.lower()
        for token in list(expected["answer_must_not_include"] or []):
            assert str(token).lower() not in answer_text
    if expected.get("should_clarify_or_use_knowledge"):
        assert result.should_clarify is True or result.public_workflow == "knowledge"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_customer_scenario_matrix(case: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    harness = ChatEvalHarness(monkeypatch)
    result = await harness.run_messages(case["messages"])
    _assert_expected(result, dict(case["expected"] or {}))
