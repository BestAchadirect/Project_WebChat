from __future__ import annotations

import pytest

from tests.evaluation.chat.eval_harness import ChatEvalHarness


pytestmark = pytest.mark.evaluation


@pytest.mark.asyncio
async def test_context_awareness_preserves_product_type_for_gold_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = ChatEvalHarness(monkeypatch)

    first = await harness.run_message("show me labret")
    second = await harness.run_message("gold one")

    assert first.filters["product_type"] == "labret"
    assert second.filters["product_type"] == "labret"
    assert second.filters["material"] == "gold"
    assert second.should_clarify is False


@pytest.mark.asyncio
async def test_context_awareness_resumes_pending_product_question_after_product_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = ChatEvalHarness(monkeypatch)

    first = await harness.run_message("where is it made?")
    second = await harness.run_message("DMBJ38")

    assert first.pending_task_type == "product_origin_question"
    assert first.missing_slot == "product_anchor"
    assert second.pending_task_type is None
    assert second.product_anchor == "DMBJ38"


@pytest.mark.asyncio
async def test_context_awareness_short_followup_without_previous_context_clarifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = ChatEvalHarness(monkeypatch)

    result = await harness.run_message("what about it?")

    assert result.should_clarify is True


@pytest.mark.asyncio
async def test_context_awareness_narrowing_previous_product_search_keeps_labret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = ChatEvalHarness(monkeypatch)

    await harness.run_message("show me labret")
    result = await harness.run_message("what about gold?")

    assert result.filters["product_type"] == "labret"
    assert result.filters["material"] == "gold"
