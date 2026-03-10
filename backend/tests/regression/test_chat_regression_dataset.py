from pathlib import Path

import pytest

pytest.importorskip("pydantic_settings")

from app.services.chat import regression_eval


DATASET_PATH = Path(__file__).parent / "data" / "chat_regression_cases.json"


@pytest.mark.regression
@pytest.mark.parametrize("case", regression_eval.load_regression_cases(DATASET_PATH), ids=lambda case: case["name"])
def test_chat_regression_dataset_cases(case) -> None:
    result = regression_eval.evaluate_case(case)
    assert result["passed"], result["mismatches"]


def test_chat_regression_suite_summary_counts_dataset() -> None:
    cases = regression_eval.load_regression_cases(DATASET_PATH)
    summary = regression_eval.run_regression_suite(cases)

    assert summary["total"] == len(cases)
    assert summary["failed"] == 0
    assert summary["by_kind"]["detail_parse"] >= 1
    assert summary["by_kind"]["follow_up_generation"] >= 1
