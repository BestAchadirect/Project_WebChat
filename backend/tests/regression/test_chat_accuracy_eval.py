from pathlib import Path

import pytest

pytest.importorskip("pydantic_settings")

from app.services.chat import accuracy_eval


PRODUCT_DATASET_PATH = Path(__file__).parent / "data" / "product_accuracy_cases.json"
FAQ_DATASET_PATH = Path(__file__).parent / "data" / "faq_accuracy_cases.json"


@pytest.mark.regression
@pytest.mark.parametrize(
    "case",
    accuracy_eval.load_accuracy_cases([PRODUCT_DATASET_PATH, FAQ_DATASET_PATH]),
    ids=lambda case: case["id"],
)
def test_chat_accuracy_dataset_cases(case) -> None:
    result = accuracy_eval.evaluate_case(case)
    assert result["passed"], result["mismatches"]


def test_chat_accuracy_suite_summary_counts_dataset() -> None:
    cases = accuracy_eval.load_accuracy_cases([PRODUCT_DATASET_PATH, FAQ_DATASET_PATH])
    summary = accuracy_eval.run_accuracy_suite(cases)

    assert summary["total"] == len(cases)
    assert summary["failed"] == 0
    assert summary["by_suite"]["product"] >= 1
    assert summary["by_suite"]["faq"] >= 1
    assert summary["by_kind"]["response_contract"] >= 1


def test_chat_accuracy_suite_can_overlay_external_actual_results() -> None:
    cases = [
        {
            "id": "faq_overlay_case",
            "name": "faq_overlay_case",
            "suite": "faq",
            "bucket": "policy_contract",
            "kind": "response_contract",
            "expected": {
                "workflow": "knowledge",
                "reply_must_include": ["refund"],
                "product_count_max": 0,
            },
        }
    ]
    actual_results = {
        "faq_overlay_case": {
            "routing": {"workflow": "knowledge"},
            "reply_text": "Refund requests are reviewed by the support team.",
            "follow_up_questions": [],
            "sources": [{"title": "Refund Policy"}],
            "product_carousel": [],
            "debug": {},
        }
    }

    summary = accuracy_eval.run_accuracy_suite(cases, actual_results=actual_results)

    assert summary["failed"] == 0
    assert summary["passed"] == 1


def test_chat_accuracy_suite_reads_explicit_follow_ups_from_actual_results() -> None:
    cases = [
        {
            "id": "component_contract_case",
            "name": "component_contract_case",
            "suite": "product",
            "bucket": "component_contract",
            "kind": "response_contract",
            "expected": {
                "workflow": "catalog",
                "reply_must_include": ["titanium"],
                "follow_ups_include": ["See more titanium labrets"],
                "top_product_skus_include_any": ["SKU-1"],
            },
        }
    ]
    actual_results = {
        "component_contract_case": {
            "routing": {"workflow": "catalog"},
            "follow_up_questions": ["See more titanium labrets"],
            "components": [
                {"type": "assistant_message", "data": {"text": "I found titanium options for you."}},
                {
                    "type": "product_cards",
                    "data": {"cards": [{"sku": "SKU-1", "title": "Titanium Labret"}]},
                },
            ],
            "sources": [],
            "debug": {},
        }
    }

    summary = accuracy_eval.run_accuracy_suite(cases, actual_results=actual_results)

    assert summary["failed"] == 0
    assert summary["passed"] == 1
