from __future__ import annotations

import pytest

from tests.evaluation.chat.eval_harness import ChatEvalHarness
from tests.evaluation.chat.scenario_loader import load_scenarios


pytestmark = pytest.mark.evaluation

ADVERSARIAL_CASES = load_scenarios("adversarial_messages.yaml")
UNCERTAINTY_PHRASES = ("probably", "i think", "might be", "assume")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ADVERSARIAL_CASES, ids=lambda case: case["id"])
async def test_adversarial_messages_stay_grounded(
    case: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = ChatEvalHarness(monkeypatch)
    result = await harness.run_messages(case["messages"])
    expected = dict(case["expected"] or {})

    if "should_clarify" in expected:
        assert result.should_clarify is bool(expected["should_clarify"])
    if "filters" in expected:
        for key, value in dict(expected["filters"] or {}).items():
            assert result.filters.get(str(key)) == value
    if "should_not_force_filters" in expected:
        for key in list(expected["should_not_force_filters"] or []):
            assert str(key) not in result.filters

    answer_text = result.answer_text.lower()
    for phrase in UNCERTAINTY_PHRASES:
        assert phrase not in answer_text


@pytest.mark.asyncio
async def test_grounded_detail_answer_avoids_uncertainty_phrases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = ChatEvalHarness(monkeypatch)
    result = await harness.run_message("show details for DMBJ38")

    answer_text = result.answer_text.lower()
    assert result.product_anchor == "DMBJ38"
    for phrase in UNCERTAINTY_PHRASES:
        assert phrase not in answer_text


@pytest.mark.asyncio
async def test_missing_product_data_clarifies_or_states_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = ChatEvalHarness(monkeypatch)
    result = await harness.run_message("show details for UNKNOWN-404")

    answer_text = result.answer_text.lower()
    assert result.should_clarify is True or any(
        token in answer_text for token in ("couldn't find", "could not find", "exact match", "clarify")
    )
    for phrase in UNCERTAINTY_PHRASES:
        assert phrase not in answer_text
