import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import app.services.chat.observability.regression_eval as regression_eval
from app.services.chat.parsing.parser_rule_types import ParserRuleSet


SUPPORTED_CONTRACT_KINDS = {"response_contract"}


def _regression_data_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "tests" / "regression" / "data"


def default_routing_dataset_path() -> Path:
    return _regression_data_dir() / "chat_routing_cases.json"


def default_parser_dataset_path() -> Path:
    return _regression_data_dir() / "chat_parser_cases.json"


def default_response_dataset_path() -> Path:
    return _regression_data_dir() / "chat_response_contract_cases.json"


def default_dataset_paths(*, suite: str = "all") -> List[Path]:
    suite_norm = str(suite or "all").strip().lower()
    suite_map = {
        "routing": [default_routing_dataset_path()],
        "parser": [default_parser_dataset_path()],
        "response": [default_response_dataset_path()],
        "all": [
            default_routing_dataset_path(),
            default_parser_dataset_path(),
            default_response_dataset_path(),
        ],
    }
    if suite_norm not in suite_map:
        raise ValueError(f"unsupported accuracy suite: {suite}")
    return list(suite_map[suite_norm])


def load_accuracy_cases(paths: Optional[Sequence[str | Path]] = None, *, suite: str = "all") -> List[Dict[str, Any]]:
    dataset_paths = [Path(item) for item in list(paths or [])] or default_dataset_paths(suite=suite)
    cases: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    suite_norm = str(suite or "all").strip().lower()
    for dataset_path in dataset_paths:
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"accuracy dataset must be a list: {dataset_path}")
        for raw_case in payload:
            case = dict(raw_case or {})
            case_id = str(case.get("id") or "").strip()
            if not case_id:
                raise ValueError(f"accuracy case missing id: {dataset_path}")
            if case_id in seen_ids:
                raise ValueError(f"duplicate accuracy case id: {case_id}")
            case_suite = str(case.get("suite") or "").strip().lower() or _infer_suite_from_path(dataset_path)
            if suite_norm != "all" and case_suite != suite_norm:
                continue
            seen_ids.add(case_id)
            case.setdefault("suite", case_suite)
            case.setdefault("dataset_path", str(dataset_path))
            cases.append(case)
    return cases


def load_actual_results(path: str | Path) -> Dict[str, Dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return {str(key): _normalize_actual_result(value) for key, value in payload.items()}
    if isinstance(payload, list):
        out: Dict[str, Dict[str, Any]] = {}
        for raw in payload:
            item = dict(raw or {})
            case_id = str(item.get("id") or item.get("case_id") or "").strip()
            if not case_id:
                raise ValueError("actual result item missing id")
            out[case_id] = _normalize_actual_result(item.get("response", item))
        return out
    raise ValueError("actual results payload must be a dict or list")


def evaluate_case(
    case: Dict[str, Any],
    *,
    actual_results: Optional[Dict[str, Dict[str, Any]]] = None,
    parser_rules: ParserRuleSet | None = None,
    alias_map: Dict[str, Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    kind = str(case.get("kind") or "").strip().lower()
    case_id = str(case.get("id") or "").strip()
    suite = str(case.get("suite") or "").strip().lower() or "unknown"
    bucket = str(case.get("bucket") or "").strip().lower() or "unbucketed"
    if kind in SUPPORTED_CONTRACT_KINDS:
        result = _evaluate_response_contract(case=case, actual_results=actual_results)
    else:
        result = regression_eval.evaluate_case(
            case,
            parser_rules=parser_rules,
            alias_map=alias_map,
        )
    result["id"] = case_id
    result["suite"] = suite
    result["bucket"] = bucket
    result["dataset_path"] = str(case.get("dataset_path") or "")
    return result


def run_accuracy_suite(
    cases: Sequence[Dict[str, Any]],
    *,
    actual_results: Optional[Dict[str, Dict[str, Any]]] = None,
    parser_rules: ParserRuleSet | None = None,
    alias_map: Dict[str, Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    results = [
        evaluate_case(
            case,
            actual_results=actual_results,
            parser_rules=parser_rules,
            alias_map=alias_map,
        )
        for case in list(cases or [])
    ]
    failures = [result for result in results if not bool(result.get("passed", False))]
    by_kind = _count_by(results, "kind")
    by_suite = _count_by(results, "suite")
    by_bucket = _count_by(results, "bucket")
    return {
        "total": len(results),
        "failed": len(failures),
        "passed": len(results) - len(failures),
        "by_kind": by_kind,
        "by_suite": by_suite,
        "by_bucket": by_bucket,
        "token_usage_estimate": _summarize_token_usage(results),
        "results": results,
        "failures": failures,
    }


def _evaluate_response_contract(
    *,
    case: Dict[str, Any],
    actual_results: Optional[Dict[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    case_id = str(case.get("id") or "").strip() or "response_contract_case"
    actual_response = None
    if isinstance(actual_results, dict):
        raw_actual = actual_results.get(case_id)
        if raw_actual is not None:
            actual_response = _normalize_actual_result(raw_actual)
    if actual_response is None:
        actual_response = _normalize_actual_result(case.get("actual_response", {}))
    expected = dict(case.get("expected") or {})
    if not actual_response:
        mismatches = ["actual response missing"]
        return {
            "name": case_id,
            "kind": "response_contract",
            "passed": False,
            "actual": {},
            "expected": expected,
            "mismatches": mismatches,
        }

    actual = {
        "workflow": str(actual_response.get("workflow") or ""),
        "reply_text": str(actual_response.get("reply_text") or ""),
        "follow_up_questions": list(actual_response.get("follow_up_questions") or []),
        "source_count": int(len(list(actual_response.get("sources") or []))),
        "product_count": int(len(list(actual_response.get("product_carousel") or []))),
        "product_skus": [
            str(item.get("sku") or "")
            for item in list(actual_response.get("product_carousel") or [])
            if str(item.get("sku") or "").strip()
        ],
        "debug": dict(actual_response.get("debug") or {}),
        "token_usage_estimate": {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "by_call": [],
        },
    }
    mismatches = _compare_response_contract(actual=actual, expected=expected)
    return {
        "name": case_id,
        "kind": "response_contract",
        "passed": not mismatches,
        "actual": actual,
        "expected": expected,
        "mismatches": mismatches,
    }


def _compare_response_contract(*, actual: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    mismatches: List[str] = []
    if "workflow" in expected and str(actual.get("workflow") or "") != str(expected.get("workflow") or ""):
        mismatches.append(
            f"workflow: expected {expected.get('workflow')!r}, got {actual.get('workflow')!r}"
        )

    reply_text = str(actual.get("reply_text") or "")
    reply_text_norm = reply_text.lower()
    for token in list(expected.get("reply_must_include") or []):
        needle = str(token or "").strip().lower()
        if needle and needle not in reply_text_norm:
            mismatches.append(f"reply_text missing {token!r}")
    for token in list(expected.get("reply_must_not_include") or []):
        needle = str(token or "").strip().lower()
        if needle and needle in reply_text_norm:
            mismatches.append(f"reply_text contains forbidden {token!r}")

    follow_ups = [str(item) for item in list(actual.get("follow_up_questions") or [])]
    follow_ups_norm = [item.lower() for item in follow_ups]
    for item in list(expected.get("follow_ups_include") or []):
        if str(item).lower() not in follow_ups_norm:
            mismatches.append(f"follow_up_questions missing {item!r}")
    for item in list(expected.get("follow_ups_exclude") or []):
        if str(item).lower() in follow_ups_norm:
            mismatches.append(f"follow_up_questions contains forbidden {item!r}")

    product_skus = [str(item) for item in list(actual.get("product_skus") or [])]
    product_skus_norm = [item.lower() for item in product_skus]
    include_any = [str(item) for item in list(expected.get("top_product_skus_include_any") or []) if str(item).strip()]
    if include_any and not any(item.lower() in product_skus_norm for item in include_any):
        mismatches.append(f"product_skus missing any of {include_any!r}")
    for item in list(expected.get("top_product_skus_exclude") or []):
        if str(item).lower() in product_skus_norm:
            mismatches.append(f"product_skus contains forbidden {item!r}")

    for field_name in ("source_count", "product_count"):
        actual_value = int(actual.get(field_name) or 0)
        min_key = f"{field_name}_min"
        max_key = f"{field_name}_max"
        if min_key in expected and actual_value < int(expected[min_key]):
            mismatches.append(f"{field_name} below minimum {expected[min_key]!r}: got {actual_value!r}")
        if max_key in expected and actual_value > int(expected[max_key]):
            mismatches.append(f"{field_name} above maximum {expected[max_key]!r}: got {actual_value!r}")

    debug = dict(actual.get("debug") or {})
    for key, expected_value in dict(expected.get("debug_equals") or {}).items():
        actual_value = debug.get(key)
        if actual_value != expected_value:
            mismatches.append(f"debug.{key}: expected {expected_value!r}, got {actual_value!r}")
    return mismatches


def _component_type_value(component: Dict[str, Any]) -> str:
    raw_type = component.get("type")
    if isinstance(raw_type, dict):
        raw_type = raw_type.get("value")
    return str(getattr(raw_type, "value", raw_type) or "").strip().lower()


def _reply_text_from_components(components: List[Dict[str, Any]]) -> str:
    preferred_types = (
        "assistant_message",
        "knowledge_answer",
        "clarify",
        "error",
    )
    for component_type in preferred_types:
        for component in components:
            if _component_type_value(component) != component_type:
                continue
            data = dict(component.get("data") or {})
            if component_type == "assistant_message":
                return str(data.get("text") or "").strip()
            if component_type == "knowledge_answer":
                return str(data.get("answer") or "").strip()
            return str(data.get("message") or "").strip()
    return ""


def _quick_replies_from_components(components: List[Dict[str, Any]]) -> List[str]:
    for component in components:
        if _component_type_value(component) != "quick_replies":
            continue
        data = dict(component.get("data") or {})
        items: List[str] = []
        seen: set[str] = set()
        for raw in list(data.get("items") or []):
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(text)
        return items
    return []


def _product_carousel_from_components(components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for component in components:
        component_type = _component_type_value(component)
        data = dict(component.get("data") or {})
        if component_type == "product_cards":
            cards = [dict(item or {}) for item in list(data.get("cards") or []) if isinstance(item, dict)]
            if cards:
                return cards
        if component_type == "product_detail":
            product = data.get("product")
            if isinstance(product, dict):
                return [dict(product)]
    return []


def _normalize_actual_result(payload: Any) -> Dict[str, Any]:
    item = dict(payload or {})
    components = [dict(component or {}) for component in list(item.get("components") or []) if isinstance(component, dict)]
    reply_text = item.get("reply_text")
    if not str(reply_text or "").strip():
        reply_text = _reply_text_from_components(components)
    follow_up_questions = list(item.get("follow_up_questions") or [])
    if not follow_up_questions:
        follow_up_questions = _quick_replies_from_components(components)
    product_carousel = list(item.get("product_carousel") or [])
    if not product_carousel:
        product_carousel = _product_carousel_from_components(components)
    return {
        "workflow": dict(item.get("routing") or {}).get("workflow"),
        "reply_text": reply_text,
        "follow_up_questions": follow_up_questions,
        "sources": list(item.get("sources") or []),
        "product_carousel": product_carousel,
        "components": components,
        "debug": dict(item.get("debug") or {}),
    }


def _count_by(results: Iterable[Dict[str, Any]], field_name: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for result in results:
        key = str(result.get(field_name) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _infer_suite_from_path(path: Path) -> str:
    name = path.stem.lower()
    if "routing" in name:
        return "routing"
    if "parser" in name:
        return "parser"
    if "response" in name:
        return "response"
    return "unknown"


def _summarize_token_usage(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "by_call": [],
    }
    for result in list(results or []):
        token_usage = dict((result or {}).get("actual", {}).get("token_usage_estimate") or {})
        summary["total_prompt_tokens"] += int(token_usage.get("total_prompt_tokens", 0) or 0)
        summary["total_completion_tokens"] += int(token_usage.get("total_completion_tokens", 0) or 0)
        summary["total_tokens"] += int(token_usage.get("total_tokens", 0) or 0)
        summary["by_call"].extend(list(token_usage.get("by_call") or []))
    return summary
