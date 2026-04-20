from __future__ import annotations

import pytest

from app.services.chat.observability import accuracy_eval
from app.services.chat.observability.capture_eval import (
    build_chat_request_from_case,
    filter_capture_cases,
)


def test_filter_capture_cases_only_keeps_response_contract_cases() -> None:
    cases = accuracy_eval.load_accuracy_cases(suite="all")

    filtered = filter_capture_cases(cases)

    assert filtered
    assert {str(case["kind"]) for case in filtered} == {"response_contract"}
    assert {str(case["suite"]) for case in filtered} == {"response"}


def test_build_chat_request_from_case_uses_dataset_inputs() -> None:
    case = accuracy_eval.load_accuracy_cases(suite="response")[0]

    request = build_chat_request_from_case(case)

    assert request.message == case["inputs"]["message"]
    assert request.locale == case["inputs"]["locale"]
    assert request.user_id == f"accuracy-{case['id']}"


def test_build_chat_request_from_case_requires_message() -> None:
    with pytest.raises(ValueError, match="missing inputs.message"):
        build_chat_request_from_case({"id": "missing-message", "inputs": {"locale": "en-US"}})
