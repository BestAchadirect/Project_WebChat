import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.schemas.chat import ProductCard
from app.services.chat import follow_up_policy
from app.services.chat.detail_query_parser import DetailQueryParser
from app.services.chat.service import ChatService


def default_dataset_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tests" / "regression" / "data" / "chat_regression_cases.json"


def load_regression_cases(path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    dataset_path = Path(path) if path else default_dataset_path()
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("regression dataset must be a list")
    return [dict(item or {}) for item in payload]


def evaluate_case(case: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(case.get("kind") or "").strip().lower()
    name = str(case.get("name") or "").strip() or f"{kind}_case"
    if kind == "detail_parse":
        return _evaluate_detail_parse(case=case, name=name)
    if kind == "follow_up_generation":
        return _evaluate_follow_up_generation(case=case, name=name)
    raise ValueError(f"Unsupported regression case kind: {kind}")


def run_regression_suite(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    results = [evaluate_case(case) for case in list(cases or [])]
    failures = [result for result in results if not bool(result.get("passed", False))]
    by_kind: Dict[str, int] = {}
    for result in results:
        kind = str(result.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "total": len(results),
        "failed": len(failures),
        "passed": len(results) - len(failures),
        "by_kind": dict(sorted(by_kind.items())),
        "results": results,
        "failures": failures,
    }


def _evaluate_detail_parse(*, case: Dict[str, Any], name: str) -> Dict[str, Any]:
    parsed = DetailQueryParser.parse(
        user_text=str(case.get("user_text") or ""),
        nlu_data=dict(case.get("nlu_data") or {}),
    )
    expected = dict(case.get("expected") or {})
    actual = {
        "attribute_filters": dict(parsed.attribute_filters or {}),
        "requested_fields": list(parsed.requested_fields or []),
        "wants_image": bool(parsed.wants_image),
        "is_detail_request": bool(parsed.is_detail_request),
    }
    return _build_result(name=name, kind="detail_parse", actual=actual, expected=expected)


def _evaluate_follow_up_generation(*, case: Dict[str, Any], name: str) -> Dict[str, Any]:
    inputs = dict(case.get("inputs") or {})
    products = [
        ProductCard(
            id=uuid4(),
            object_id=str(item.get("sku") or ""),
            sku=str(item.get("sku") or ""),
            legacy_sku=[],
            name=str(item.get("name") or item.get("sku") or ""),
            description=None,
            price=float(item.get("price", 0.0) or 0.0),
            currency=str(item.get("currency") or "USD"),
            stock_status=str(item.get("stock_status") or "in_stock"),
            image_url=None,
            product_url=None,
            attributes=dict(item.get("attributes") or {}),
        )
        for item in list(inputs.get("products") or [])
    ]
    questions = follow_up_policy.build_product_follow_up_questions(
        products=products,
        attribute_filters=dict(inputs.get("attribute_filters") or {}),
        user_text=str(inputs.get("user_text") or ""),
        stopwords=ChatService._FOLLOW_UP_STOPWORDS,
        product_terms=ChatService._FOLLOW_UP_PRODUCT_TERMS,
        has_more_results=bool(inputs.get("has_more_results", False)),
        limit=int(inputs.get("limit", 4) or 4),
    )
    actual = {
        "questions": list(questions),
        "first_question": str(questions[0] if questions else ""),
    }
    expected = dict(case.get("expected") or {})
    return _build_result(name=name, kind="follow_up_generation", actual=actual, expected=expected)


def _build_result(*, name: str, kind: str, actual: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    mismatches = _compare_expected(actual=actual, expected=expected)
    return {
        "name": name,
        "kind": kind,
        "passed": not mismatches,
        "actual": actual,
        "expected": expected,
        "mismatches": mismatches,
    }


def _compare_expected(*, actual: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    mismatches: List[str] = []
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if key == "attribute_filters" and isinstance(expected_value, dict):
            for attr_key, attr_expected in expected_value.items():
                actual_attr = dict(actual_value or {}).get(attr_key)
                if actual_attr != attr_expected:
                    mismatches.append(
                        f"attribute_filters.{attr_key}: expected {attr_expected!r}, got {actual_attr!r}"
                    )
            continue
        if key == "questions_include" and isinstance(expected_value, list):
            for item in expected_value:
                if str(item) not in list(actual.get("questions") or []):
                    mismatches.append(f"questions missing {item!r}")
            continue
        if actual_value != expected_value:
            mismatches.append(f"{key}: expected {expected_value!r}, got {actual_value!r}")
    return mismatches
