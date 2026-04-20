import pytest
from dataclasses import dataclass

pytest.importorskip("pydantic_settings")

from app.services.chat.observability import accuracy_eval
from app.services.chat.parsing.parser_rule_types import ParserRuleSet, build_rule_set


@dataclass(frozen=True)
class ChatParserFixture:
    parser_rules: ParserRuleSet
    alias_map: dict[str, dict[str, str]]


_CASES_CACHE = None


def _get_cases():
    global _CASES_CACHE
    if _CASES_CACHE is None:
        _CASES_CACHE = accuracy_eval.load_accuracy_cases()
    return _CASES_CACHE


def pytest_generate_tests(metafunc):
    if "case" not in metafunc.fixturenames:
        return
    cases = _get_cases()
    metafunc.parametrize("case", cases, ids=lambda case: case["id"])


@pytest.fixture(scope="module")
def chat_parser_fixture():
    return ChatParserFixture(parser_rules=_parser_rules(), alias_map=_alias_map())


def _parser_rules() -> ParserRuleSet:
    return build_rule_set(
        requested_field_patterns={
            "price": [r"\bprice\b", r"\bcost\b", r"\bhow much\b"],
            "stock": [r"\bstock\b", r"\bavailability\b", r"\bin stock\b", r"\bout of stock\b", r"\bavailable\b"],
            "image": [r"\bimage\b", r"\bpicture\b", r"\bphoto\b", r"\bpic\b"],
            "attributes": [r"\battribute\b", r"\battributes\b", r"\bspec\b", r"\bspecs\b", r"\bdetails\b"],
        },
        value_extract_patterns={
            "outer_diameter": [
                r"\bouter diameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b",
                r"\b(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\s+outer diameter\b",
                r"\bdiameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b",
            ],
            "ring_size": [r"\bring size(?: is|=| of)?\s+(?P<value>[a-z0-9.]+)\b"],
            "opal_color": [
                r"\b(?P<value>black|white|clear|blue|red|green|purple|pink|yellow|orange|silver|gold|rose gold)\s+opal color\b"
            ],
        },
        detection_attribute_order=["jewelry_type", "material", "threading", "finish", "design", "color"],
        allowed_attribute_filters=[
            "jewelry_type",
            "material",
            "threading",
            "finish",
            "design",
            "color",
            "gauge",
            "outer_diameter",
            "ring_size",
            "opal_color",
        ],
    )


def _alias_map() -> dict[str, dict[str, str]]:
    return {
        "jewelry_type": {
            "barbell": "barbell",
            "labret": "labret",
            "ring": "ring",
            "rings": "ring",
            "hoop": "ring",
        },
        "material": {
            "titanium": "titanium",
            "implant grade titanium": "titanium g23",
            "steel": "steel",
            "gold": "gold",
        },
        "finish": {
            "sterilized": "sterilized",
            "sterilised": "sterilized",
            "sterilization": "sterilized",
            "sterilisation": "sterilized",
        },
        "design": {
            "heart": "heart",
        },
        "color": {
            "black": "black",
            "blue": "blue",
            "gold": "gold",
            "opal": "opal",
            "opal color": "opal",
        },
        "stone": {
            "opal": "opal",
        },
    }


@pytest.mark.regression
def test_chat_ai_logic_cases(case, chat_parser_fixture) -> None:
    result = accuracy_eval.evaluate_case(
        case,
        parser_rules=chat_parser_fixture.parser_rules,
        alias_map=chat_parser_fixture.alias_map,
    )
    assert result["passed"], result["mismatches"]


def test_chat_ai_logic_suite_summary(chat_parser_fixture) -> None:
    try:
        cases = _get_cases()
    except Exception as exc:
        pytest.skip(f"DB-backed AI logic dataset unavailable: {exc}")
    summary = accuracy_eval.run_accuracy_suite(
        cases,
        parser_rules=chat_parser_fixture.parser_rules,
        alias_map=chat_parser_fixture.alias_map,
    )

    assert summary["total"] == len(cases)
    assert summary["failed"] == 0
    assert summary["by_kind"]["routing_decision"] >= 1
    assert summary["by_kind"]["detail_parse"] >= 1
    assert summary["by_kind"]["follow_up_generation"] >= 1
    assert summary["by_kind"]["response_contract"] >= 1
    assert summary["by_suite"]["routing"] >= 1
    assert summary["by_suite"]["parser"] >= 1
    assert summary["by_suite"]["response"] >= 1
