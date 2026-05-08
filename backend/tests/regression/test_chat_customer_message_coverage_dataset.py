from __future__ import annotations

import json
from pathlib import Path


DATASET_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "chat_customer_message_coverage_cases.json"
)


def test_customer_message_coverage_dataset_is_well_formed() -> None:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    cases = list(payload.get("cases") or [])

    assert payload.get("version") == 1
    assert len(cases) >= 50

    seen_ids: set[str] = set()
    groups: set[str] = set()
    for case in cases:
        case_id = str(case.get("id") or "").strip()
        group = str(case.get("group") or "").strip()
        assert case_id
        assert case_id not in seen_ids
        assert group
        assert str(case.get("message") or "").strip() or list(case.get("turns") or [])
        if case.get("message"):
            assert str(case.get("expected_workflow") or "").strip() or list(case.get("expected_workflows") or [])
        for turn in list(case.get("turns") or []):
            assert str(turn.get("message") or "").strip()
            assert str(turn.get("expected_workflow") or "").strip() or list(turn.get("expected_workflows") or [])
        seen_ids.add(case_id)
        groups.add(group)

    assert {
        "catalog_basic",
        "catalog_attributes",
        "catalog_detail",
        "ambiguous_catalog",
        "knowledge",
        "mixed",
        "general_talking",
        "off_topic",
        "frustrated",
        "typos",
        "multilingual",
        "multi_turn",
    }.issubset(groups)
