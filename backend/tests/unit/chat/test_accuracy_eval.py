from __future__ import annotations

from app.services.chat.observability import accuracy_eval
from app.services.chat.observability import regression_eval


def test_accuracy_eval_default_dataset_paths_match_supported_suites() -> None:
    all_paths = accuracy_eval.default_dataset_paths(suite="all")
    routing_paths = accuracy_eval.default_dataset_paths(suite="routing")
    parser_paths = accuracy_eval.default_dataset_paths(suite="parser")
    response_paths = accuracy_eval.default_dataset_paths(suite="response")

    assert len(all_paths) == 3
    assert len(routing_paths) == 1
    assert len(parser_paths) == 1
    assert len(response_paths) == 1
    assert routing_paths[0].name == "chat_routing_cases.json"
    assert parser_paths[0].name == "chat_parser_cases.json"
    assert response_paths[0].name == "chat_response_contract_cases.json"


def test_accuracy_eval_load_accuracy_cases_filters_by_suite() -> None:
    routing_cases = accuracy_eval.load_accuracy_cases(suite="routing")
    parser_cases = accuracy_eval.load_accuracy_cases(suite="parser")
    response_cases = accuracy_eval.load_accuracy_cases(suite="response")

    assert routing_cases
    assert parser_cases
    assert response_cases
    assert {case["suite"] for case in routing_cases} == {"routing"}
    assert {case["suite"] for case in parser_cases} == {"parser"}
    assert {case["suite"] for case in response_cases} == {"response"}


def test_accuracy_eval_response_cases_include_capture_inputs() -> None:
    response_cases = accuracy_eval.load_accuracy_cases(suite="response")

    assert response_cases
    for case in response_cases:
        inputs = dict(case.get("inputs") or {})
        assert str(inputs.get("message") or "").strip()


def test_regression_eval_default_cases_exclude_response_contract_cases() -> None:
    cases = regression_eval.load_regression_cases()

    assert cases
    assert all(case["kind"] != "response_contract" for case in cases)
    assert {case["suite"] for case in cases} == {"routing", "parser"}
