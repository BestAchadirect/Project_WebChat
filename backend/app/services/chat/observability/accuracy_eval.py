import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import app.services.chat.observability.regression_eval as regression_eval
from app.services.chat.parsing.parser_rule_types import ParserRuleSet


SUPPORTED_CONTRACT_KINDS = {"response_contract", "context_contract", "long_context_contract", "adversarial_contract"}


def _regression_data_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "tests" / "regression" / "data"


def default_routing_dataset_path() -> Path:
    return _regression_data_dir() / "chat_routing_cases.json"


def default_parser_dataset_path() -> Path:
    return _regression_data_dir() / "chat_parser_cases.json"


def default_response_dataset_path() -> Path:
    return _regression_data_dir() / "chat_response_contract_cases.json"


def default_long_context_dataset_path() -> Path:
    return _regression_data_dir() / "chat_long_context_cases.json"


def default_adversarial_dataset_path() -> Path:
    return _regression_data_dir() / "chat_adversarial_cases.json"


def default_dataset_paths(*, suite: str = "all") -> List[Path]:
    suite_norm = str(suite or "all").strip().lower()
    suite_map = {
        "routing": [default_routing_dataset_path()],
        "parser": [default_parser_dataset_path()],
        "response": [default_response_dataset_path()],
        "long_context": [default_long_context_dataset_path()],
        "adversarial": [default_adversarial_dataset_path()],
        "all": [
            default_routing_dataset_path(),
            default_parser_dataset_path(),
            default_response_dataset_path(),
            default_long_context_dataset_path(),
            default_adversarial_dataset_path(),
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
        result = _evaluate_contract_case(case=case, actual_results=actual_results)
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
    by_focus_group = _count_focus_groups(results)
    return {
        "total": len(results),
        "failed": len(failures),
        "passed": len(results) - len(failures),
        "by_kind": by_kind,
        "by_suite": by_suite,
        "by_bucket": by_bucket,
        "by_focus_group": by_focus_group,
        "failure_summary": _summarize_failures(failures),
        "trend_summary": {
            "total": len(results),
            "passed": len(results) - len(failures),
            "failed": len(failures),
            "by_focus_group": by_focus_group,
        },
        "token_usage_estimate": _summarize_token_usage(results),
        "results": results,
        "failures": failures,
    }


def _evaluate_contract_case(
    *,
    case: Dict[str, Any],
    actual_results: Optional[Dict[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    case_kind = str(case.get("kind") or "").strip().lower() or "response_contract"
    case_id = str(case.get("id") or "").strip() or "response_contract_case"
    actual_response = None
    if isinstance(actual_results, dict):
        raw_actual = actual_results.get(case_id)
        if raw_actual:
            actual_response = _coerce_actual_response(raw_actual)
    if actual_response is None:
        fallback_payload = case.get("fallback_actual_response", case.get("actual_response"))
        if fallback_payload:
            actual_response = _coerce_actual_response(fallback_payload)
    expected = dict(case.get("expected") or {})
    if not actual_response:
        mismatches = ["actual response missing"]
        return {
            "name": case_id,
            "kind": case_kind,
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
        "component_types": [
            _component_type_value(component)
            for component in list(actual_response.get("components") or [])
            if _component_type_value(component)
        ],
        "source_titles": [
            str(item.get("title") or "").strip()
            for item in list(actual_response.get("sources") or [])
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ],
        "source_snippets": [
            str(item.get("content_snippet") or "").strip()
            for item in list(actual_response.get("sources") or [])
            if isinstance(item, dict) and str(item.get("content_snippet") or "").strip()
        ],
        "context": _build_context_summary(actual_response),
        "debug": dict(actual_response.get("debug") or {}),
        "token_usage_estimate": {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "by_call": [],
        },
    }
    if case_kind == "long_context_contract":
        turns = list(case.get("turns") or case.get("history") or [])
        actual["turn_count"] = int(len(turns))
    mismatches = _compare_response_contract(actual=actual, expected=expected)
    return {
        "name": case_id,
        "kind": case_kind,
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

    component_types = [str(item) for item in list(actual.get("component_types") or [])]
    component_types_norm = [item.lower() for item in component_types]
    for item in list(expected.get("required_component_types") or []):
        if str(item).lower() not in component_types_norm:
            mismatches.append(f"component_types missing {item!r}")
    for item in list(expected.get("forbidden_component_types") or []):
        if str(item).lower() in component_types_norm:
            mismatches.append(f"component_types contains forbidden {item!r}")
    exact_component_types = [str(item).lower() for item in list(expected.get("component_types_exact") or []) if str(item).strip()]
    if exact_component_types and component_types_norm != exact_component_types:
        mismatches.append(
            f"component_types exact mismatch: expected {exact_component_types!r}, got {component_types_norm!r}"
        )

    source_titles = [str(item) for item in list(actual.get("source_titles") or [])]
    source_titles_norm = [item.lower() for item in source_titles]
    include_any_titles = [str(item) for item in list(expected.get("source_titles_include_any") or []) if str(item).strip()]
    if include_any_titles and not any(item.lower() in source_titles_norm for item in include_any_titles):
        mismatches.append(f"source_titles missing any of {include_any_titles!r}")
    include_all_titles = [str(item) for item in list(expected.get("source_titles_include_all") or []) if str(item).strip()]
    for item in include_all_titles:
        if item.lower() not in source_titles_norm:
            mismatches.append(f"source_titles missing required {item!r}")
    exact_source_titles = [str(item) for item in list(expected.get("source_titles_exact") or []) if str(item).strip()]
    if exact_source_titles and source_titles != exact_source_titles:
        mismatches.append(f"source_titles exact mismatch: expected {exact_source_titles!r}, got {source_titles!r}")
    for item in list(expected.get("source_titles_exclude") or []):
        if str(item).lower() in source_titles_norm:
            mismatches.append(f"source_titles contains forbidden {item!r}")
    source_snippets = [str(item) for item in list(actual.get("source_snippets") or [])]
    source_snippets_norm = [item.lower() for item in source_snippets]
    include_any_snippets = [str(item) for item in list(expected.get("source_snippets_include_any") or []) if str(item).strip()]
    if include_any_snippets and not any(
        any(needle.lower() in snippet for snippet in source_snippets_norm)
        for needle in include_any_snippets
    ):
        mismatches.append(f"source_snippets missing any of {include_any_snippets!r}")
    include_all_snippets = [str(item) for item in list(expected.get("source_snippets_include_all") or []) if str(item).strip()]
    for item in include_all_snippets:
        if not any(item.lower() in snippet for snippet in source_snippets_norm):
            mismatches.append(f"source_snippets missing required {item!r}")
    for item in list(expected.get("source_snippets_exclude") or []):
        if any(str(item).lower() in snippet for snippet in source_snippets_norm):
            mismatches.append(f"source_snippets contains forbidden {item!r}")

    product_skus = [str(item) for item in list(actual.get("product_skus") or [])]
    product_skus_norm = [item.lower() for item in product_skus]
    include_any = [str(item) for item in list(expected.get("top_product_skus_include_any") or []) if str(item).strip()]
    if include_any and not any(item.lower() in product_skus_norm for item in include_any):
        mismatches.append(f"product_skus missing any of {include_any!r}")
    include_all_skus = [str(item) for item in list(expected.get("top_product_skus_include_all") or []) if str(item).strip()]
    for item in include_all_skus:
        if item.lower() not in product_skus_norm:
            mismatches.append(f"product_skus missing required {item!r}")
    exact_skus = [str(item) for item in list(expected.get("top_product_skus_exact") or []) if str(item).strip()]
    if exact_skus and product_skus != exact_skus:
        mismatches.append(f"product_skus exact mismatch: expected {exact_skus!r}, got {product_skus!r}")
    for item in list(expected.get("top_product_skus_exclude") or []):
        if str(item).lower() in product_skus_norm:
            mismatches.append(f"product_skus contains forbidden {item!r}")

    for field_name in ("source_count", "product_count", "turn_count"):
        actual_value = int(actual.get(field_name) or 0)
        min_key = f"{field_name}_min"
        max_key = f"{field_name}_max"
        if min_key in expected and actual_value < int(expected[min_key]):
            mismatches.append(f"{field_name} below minimum {expected[min_key]!r}: got {actual_value!r}")
        if max_key in expected and actual_value > int(expected[max_key]):
            mismatches.append(f"{field_name} above maximum {expected[max_key]!r}: got {actual_value!r}")

    context_expected = expected.get("context")
    if isinstance(context_expected, dict):
        mismatches.extend(
            _compare_context_contract(
                actual=dict(actual.get("context") or {}),
                expected=dict(context_expected),
            )
        )

    debug = dict(actual.get("debug") or {})
    for key, expected_value in dict(expected.get("debug_equals") or {}).items():
        actual_value = _lookup_debug_value(debug=debug, key=str(key))
        if actual_value != expected_value:
            mismatches.append(f"debug.{key}: expected {expected_value!r}, got {actual_value!r}")
    return mismatches


def _build_context_summary(actual_response: Dict[str, Any]) -> Dict[str, Any]:
    product_cards = [dict(item or {}) for item in list(actual_response.get("product_carousel") or []) if isinstance(item, dict)]
    sources = [dict(item or {}) for item in list(actual_response.get("sources") or []) if isinstance(item, dict)]
    product_skus = [
        str(item.get("sku") or "").strip()
        for item in product_cards
        if str(item.get("sku") or "").strip()
    ]
    source_titles = [
        str(item.get("title") or "").strip()
        for item in sources
        if str(item.get("title") or "").strip()
    ]
    if product_skus and source_titles:
        anchor_type = "mixed"
    elif product_skus:
        anchor_type = "product"
    elif source_titles:
        anchor_type = "knowledge"
    else:
        anchor_type = "none"
    return {
        "anchor_type": anchor_type,
        "primary_product_sku": product_skus[0] if product_skus else "",
        "primary_source_title": source_titles[0] if source_titles else "",
        "product_skus": product_skus,
        "source_titles": source_titles,
    }


def _compare_context_contract(*, actual: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    mismatches: List[str] = []

    if "anchor_type" in expected:
        expected_anchor_type = str(expected.get("anchor_type") or "").strip().lower()
        actual_anchor_type = str(actual.get("anchor_type") or "").strip().lower()
        if actual_anchor_type != expected_anchor_type:
            mismatches.append(
                f"context.anchor_type: expected {expected_anchor_type!r}, got {actual_anchor_type!r}"
            )

    if "primary_product_sku" in expected:
        expected_sku = str(expected.get("primary_product_sku") or "").strip()
        actual_sku = str(actual.get("primary_product_sku") or "").strip()
        if actual_sku != expected_sku:
            mismatches.append(
                f"context.primary_product_sku: expected {expected_sku!r}, got {actual_sku!r}"
            )

    if "primary_source_title" in expected:
        expected_title = str(expected.get("primary_source_title") or "").strip()
        actual_title = str(actual.get("primary_source_title") or "").strip()
        if actual_title != expected_title:
            mismatches.append(
                f"context.primary_source_title: expected {expected_title!r}, got {actual_title!r}"
            )

    product_skus = [str(item) for item in list(actual.get("product_skus") or [])]
    source_titles = [str(item) for item in list(actual.get("source_titles") or [])]
    product_skus_norm = [item.lower() for item in product_skus]
    source_titles_norm = [item.lower() for item in source_titles]

    exact_product_skus = [str(item) for item in list(expected.get("product_skus_exact") or []) if str(item).strip()]
    if exact_product_skus and product_skus != exact_product_skus:
        mismatches.append(
            f"context.product_skus exact mismatch: expected {exact_product_skus!r}, got {product_skus!r}"
        )
    for item in list(expected.get("product_skus_include_any") or []):
        needle = str(item or "").strip().lower()
        if needle and needle not in product_skus_norm:
            mismatches.append(f"context.product_skus missing {item!r}")
    for item in list(expected.get("product_skus_exclude") or []):
        needle = str(item or "").strip().lower()
        if needle and needle in product_skus_norm:
            mismatches.append(f"context.product_skus contains forbidden {item!r}")

    exact_source_titles = [str(item) for item in list(expected.get("source_titles_exact") or []) if str(item).strip()]
    if exact_source_titles and source_titles != exact_source_titles:
        mismatches.append(
            f"context.source_titles exact mismatch: expected {exact_source_titles!r}, got {source_titles!r}"
        )
    for item in list(expected.get("source_titles_include_any") or []):
        needle = str(item or "").strip().lower()
        if needle and needle not in source_titles_norm:
            mismatches.append(f"context.source_titles missing {item!r}")
    for item in list(expected.get("source_titles_exclude") or []):
        needle = str(item or "").strip().lower()
        if needle and needle in source_titles_norm:
            mismatches.append(f"context.source_titles contains forbidden {item!r}")

    return mismatches


def _lookup_debug_value(*, debug: Dict[str, Any], key: str) -> Any:
    current: Any = dict(debug or {})
    for part in str(key or "").split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _component_type_value(component: Dict[str, Any]) -> str:
    raw_type = component.get("type")
    if isinstance(raw_type, dict):
        raw_type = raw_type.get("value")
    return str(getattr(raw_type, "value", raw_type) or "").strip().lower()


def _component_data(component: Dict[str, Any]) -> Dict[str, Any]:
    data = component.get("data")
    return dict(data or {}) if isinstance(data, dict) else {}


def _is_follow_up_text_component(component: Dict[str, Any]) -> bool:
    if _component_type_value(component) != "assistant_message":
        return False
    data = _component_data(component)
    return str(data.get("placement") or "").strip().lower() == "after_quick_replies"


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


def _is_question_like_follow_up(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    starters = (
        "how ",
        "what ",
        "when ",
        "where ",
        "why ",
        "who ",
        "which ",
        "can ",
        "could ",
        "would ",
        "should ",
        "do ",
        "does ",
        "did ",
        "is ",
        "are ",
        "will ",
        "may ",
    )
    return lowered.endswith("?") or lowered.startswith(starters)


def _reconstruct_follow_up_label(text: str) -> str:
    label = str(text or "").strip()
    if not label:
        return ""
    label = label.rstrip(" .")
    if _is_question_like_follow_up(label):
        return label if label.endswith("?") else f"{label}?"
    if label.lower().startswith(("try ", "show ", "see ", "view ", "browse ")):
        return label
    return f"Try {label}"


def _follow_up_text_questions_from_components(components: List[Dict[str, Any]]) -> List[str]:
    questions: List[str] = []
    seen: set[str] = set()
    for component in components:
        if not _is_follow_up_text_component(component):
            continue
        text = str(_component_data(component).get("text") or "").strip()
        if not text:
            continue
        for raw_line in text.splitlines():
            line = str(raw_line or "").strip()
            if not line.startswith("-"):
                continue
            label = _reconstruct_follow_up_label(line.lstrip("-").strip())
            key = label.lower()
            if not label or key in seen:
                continue
            seen.add(key)
            questions.append(label)
    return questions


def _quick_replies_from_components(components: List[Dict[str, Any]]) -> List[str]:
    for component in components:
        if _component_type_value(component) != "quick_replies":
            continue
        data = _component_data(component)
        items: List[str] = []
        seen: set[str] = set()
        for raw in list(data.get("items") or []):
            if isinstance(raw, dict):
                text = str(
                    raw.get("label") or raw.get("text") or raw.get("question") or raw.get("message") or ""
                ).strip()
            else:
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
    synthesized_follow_ups = _follow_up_text_questions_from_components(components)
    reply_text = item.get("reply_text")
    if not str(reply_text or "").strip():
        reply_text = _reply_text_from_components(components)
    follow_up_questions = list(item.get("follow_up_questions") or [])
    if not follow_up_questions:
        follow_up_questions = _quick_replies_from_components(components)
    if not follow_up_questions:
        follow_up_questions = synthesized_follow_ups
    normalized_components = [component for component in components if not _is_follow_up_text_component(component)]
    if (
        follow_up_questions
        and not any(_component_type_value(component) == "quick_replies" for component in normalized_components)
    ):
        normalized_components.append(
            {
                "type": "quick_replies",
                "data": {"items": list(follow_up_questions)},
            }
        )
    product_carousel = list(item.get("product_carousel") or [])
    if not product_carousel:
        product_carousel = _product_carousel_from_components(normalized_components)
    return {
        "workflow": dict(item.get("routing") or {}).get("workflow"),
        "reply_text": reply_text,
        "follow_up_questions": follow_up_questions,
        "sources": list(item.get("sources") or []),
        "product_carousel": product_carousel,
        "components": normalized_components,
        "debug": dict(item.get("debug") or {}),
    }


def _coerce_actual_response(payload: Any) -> Dict[str, Any]:
    item = dict(payload or {})
    if (
        "workflow" in item
        and "reply_text" in item
        and "follow_up_questions" in item
        and "sources" in item
        and "product_carousel" in item
    ):
        return item
    return _normalize_actual_result(item)


def _count_by(results: Iterable[Dict[str, Any]], field_name: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for result in results:
        key = str(result.get(field_name) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _count_focus_groups(results: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for result in results:
        kind = str(result.get("kind") or "").strip().lower()
        group = "other"
        if kind.endswith("_contract"):
            group = kind.removesuffix("_contract")
        counts[group] = counts.get(group, 0) + 1
    return dict(sorted(counts.items()))


def _infer_suite_from_path(path: Path) -> str:
    name = path.stem.lower()
    if "routing" in name:
        return "routing"
    if "parser" in name:
        return "parser"
    if "response" in name:
        return "response"
    if "long_context" in name or "long-context" in name:
        return "long_context"
    if "adversarial" in name:
        return "adversarial"
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


def _summarize_failures(failures: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    failure_list = list(failures or [])
    summary = {
        "total": len(failure_list),
        "by_kind": _count_by(failure_list, "kind"),
        "by_suite": _count_by(failure_list, "suite"),
        "by_bucket": _count_by(failure_list, "bucket"),
        "by_focus_group": _count_focus_groups(failure_list),
        "top_mismatch_signatures": [],
    }
    clusters: Dict[str, Dict[str, Any]] = {}
    for failure in failure_list:
        mismatches = [
            str(item).strip()
            for item in list(failure.get("mismatches") or [])
            if str(item).strip()
        ]
        signature = mismatches[0] if mismatches else "unspecified failure"
        cluster = clusters.setdefault(
            signature,
            {
                "signature": signature,
                "count": 0,
                "case_ids": [],
                "kinds": [],
                "suites": [],
                "buckets": [],
                "examples": [],
            },
        )
        cluster["count"] += 1
        case_id = str(failure.get("id") or failure.get("name") or "").strip()
        if case_id and case_id not in cluster["case_ids"]:
            cluster["case_ids"].append(case_id)
        kind = str(failure.get("kind") or "").strip()
        if kind and kind not in cluster["kinds"]:
            cluster["kinds"].append(kind)
        suite = str(failure.get("suite") or "").strip()
        if suite and suite not in cluster["suites"]:
            cluster["suites"].append(suite)
        bucket = str(failure.get("bucket") or "").strip()
        if bucket and bucket not in cluster["buckets"]:
            cluster["buckets"].append(bucket)
        if mismatches and len(cluster["examples"]) < 3:
            cluster["examples"].append(mismatches)

    top_clusters = sorted(
        clusters.values(),
        key=lambda item: (-int(item["count"]), str(item["signature"])),
    )
    for cluster in top_clusters:
        cluster["case_ids"] = sorted(cluster["case_ids"])
        cluster["kinds"] = sorted(cluster["kinds"])
        cluster["suites"] = sorted(cluster["suites"])
        cluster["buckets"] = sorted(cluster["buckets"])
    summary["top_mismatch_signatures"] = top_clusters[:5]
    return summary
