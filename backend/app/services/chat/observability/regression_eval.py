import json
import asyncio
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from app.schemas.chat import ProductCard
from app.services.ai.llm_service import llm_service
import app.services.chat.retrieval.follow_up_policy as follow_up_policy
from app.services.chat.observability import runtime_metrics
from app.services.chat.parsing.detail_query_parser import DetailQueryParser
from app.services.chat.parsing.parser_rule_types import ParserRuleSet
from app.services.chat.routing.decision_engine import build_decision_state
from app.services.chat.routing.understanding import build_understanding_result
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.chat.service import ChatService


def _regression_data_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "tests" / "regression" / "data"


def default_dataset_paths() -> List[Path]:
    return [
        _regression_data_dir() / "chat_routing_cases.json",
        _regression_data_dir() / "chat_parser_cases.json",
    ]


def default_dataset_path() -> Path:
    return default_dataset_paths()[0]


def load_regression_cases(path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    dataset_paths = [Path(path)] if path else default_dataset_paths()
    cases: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for dataset_path in dataset_paths:
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"regression dataset must be a list: {dataset_path}")
        for raw in payload:
            case = dict(raw or {})
            case_id = str(case.get("id") or "").strip()
            if not case_id:
                raise ValueError(f"regression case missing id: {dataset_path}")
            if case_id in seen_ids:
                raise ValueError(f"duplicate regression case id: {case_id}")
            seen_ids.add(case_id)
            case.setdefault("dataset_path", str(dataset_path))
            cases.append(case)
    return cases


def evaluate_case(
    case: Dict[str, Any],
    *,
    parser_rules: ParserRuleSet | None = None,
    alias_map: Dict[str, Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    kind = str(case.get("kind") or "").strip().lower()
    name = str(case.get("name") or "").strip() or f"{kind}_case"
    if kind == "detail_parse":
        return _evaluate_detail_parse(case=case, name=name, parser_rules=parser_rules, alias_map=alias_map)
    if kind == "follow_up_generation":
        return _evaluate_follow_up_generation(case=case, name=name)
    if kind == "routing_decision":
        return _evaluate_routing_decision(case=case, name=name)
    raise ValueError(f"Unsupported regression case kind: {kind}")


def run_regression_suite(
    cases: List[Dict[str, Any]],
    *,
    parser_rules: ParserRuleSet | None = None,
    alias_map: Dict[str, Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    results = [
        evaluate_case(case, parser_rules=parser_rules, alias_map=alias_map)
        for case in list(cases or [])
    ]
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
        "token_usage_estimate": _summarize_token_usage(results),
        "results": results,
        "failures": failures,
    }


def _evaluate_detail_parse(
    *,
    case: Dict[str, Any],
    name: str,
    parser_rules: ParserRuleSet | None = None,
    alias_map: Dict[str, Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    llm_response = dict(case.get("llm_response") or {})

    async def fake_infer_detail_query(**kwargs: Any) -> Any:
        del kwargs
        return SimpleNamespace(
            requested_fields=list(llm_response.get("requested_fields") or []),
            attribute_filters=dict(llm_response.get("attribute_filters") or {}),
            wants_image=bool(llm_response.get("wants_image", False)),
            semantic_hints=list(llm_response.get("semantic_hints") or []),
            clarify_focus=str(llm_response.get("clarify_focus") or ""),
            confidence=float(llm_response.get("confidence", 0.91) or 0.91),
        )

    with ExitStack() as stack:
        if llm_response:
            stack.enter_context(
                patch(
                    "app.services.chat.parsing.detail_query_parser.infer_detail_query",
                    fake_infer_detail_query,
                )
            )
        parsed = asyncio.run(
            DetailQueryParser.parse_async(
                user_text=str(case.get("user_text") or ""),
                nlu_data=dict(case.get("nlu_data") or {}),
                alias_map=alias_map,
                parser_rules=parser_rules,
            )
        )
    expected = dict(case.get("expected") or {})
    actual = {
        "attribute_filters": dict(parsed.attribute_filters or {}),
        "requested_fields": list(parsed.requested_fields or []),
        "wants_image": bool(parsed.wants_image),
        "is_detail_request": bool(parsed.is_detail_request),
        "token_usage_estimate": _empty_token_usage_estimate(),
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
        has_more_results=bool(inputs.get("has_more_results", False)),
        limit=int(inputs.get("limit", 4) or 4),
    )
    actual = {
        "questions": list(questions),
        "first_question": str(questions[0] if questions else ""),
        "token_usage_estimate": _empty_token_usage_estimate(),
    }
    expected = dict(case.get("expected") or {})
    return _build_result(name=name, kind="follow_up_generation", actual=actual, expected=expected)


def _evaluate_routing_decision(*, case: Dict[str, Any], name: str) -> Dict[str, Any]:
    inputs = dict(case.get("inputs") or {})
    payloads = list(case.get("understanding_llm_responses") or [])
    if not payloads and case.get("understanding_llm_response") is not None:
        payloads = [case.get("understanding_llm_response")]
    expected = dict(case.get("expected") or {})
    if not payloads:
        internal_workflow = str(expected.get("workflow_hypothesis") or expected.get("internal_workflow") or "clarify")
        payloads = [
            {
                "workflow_hypothesis": internal_workflow,
                "needs_products": bool(expected.get("needs_products")),
                "needs_knowledge": bool(expected.get("needs_knowledge")),
                "store_overview_request": bool(expected.get("store_overview_request")),
                "knowledge_query": str(expected.get("knowledge_query") or ""),
                "reason": str(expected.get("reason") or internal_workflow),
                "confidence": float(expected.get("confidence") or 0.0),
            }
        ]

    calls: Dict[str, int] = {"count": 0}
    token_usage_estimate = _empty_token_usage_estimate()

    async def fake_generate_chat_json(**kwargs: Any) -> Dict[str, Any]:
        index = min(calls["count"], len(payloads) - 1)
        calls["count"] += 1
        messages = list(kwargs.get("messages") or [])
        usage_kind = str(kwargs.get("usage_kind") or "chat_json").strip() or "chat_json"
        payload = payloads[index]
        _record_estimated_token_usage(
            token_usage_estimate,
            kind=usage_kind,
            messages=messages,
            payload=None if (isinstance(payload, dict) and str(payload.get("error") or "").strip()) else payload,
        )
        if isinstance(payload, dict) and str(payload.get("error") or "").strip():
            error = str(payload.get("error") or "").strip().lower()
            if error in {"timeout", "timeouterror"}:
                raise asyncio.TimeoutError()
            raise RuntimeError(str(payload.get("error") or "understanding_error"))
        return dict(payload or {})

    capability_overrides = dict(case.get("capabilities") or {})
    capabilities = replace(
        build_chat_runtime_capabilities(),
        agentic_function_calling_enabled=bool(
            capability_overrides.get("agentic_function_calling_enabled", True)
        ),
        agentic_allowed_channels=str(capability_overrides.get("agentic_allowed_channels", "widget")),
    )

    with ExitStack() as stack:
        if payloads:
            stack.enter_context(patch.object(llm_service, "generate_chat_json", fake_generate_chat_json))
        understanding = asyncio.run(
            build_understanding_result(
                user_text=str(inputs.get("text") or ""),
                channel=str(inputs.get("channel") or "widget"),
                locale=str(inputs.get("locale") or "en-US"),
                sku_tokens=list(inputs.get("sku_tokens") or []),
            )
        )
        decision_state = build_decision_state(
            understanding=understanding,
            user_text=str(inputs.get("text") or ""),
            channel=str(inputs.get("channel") or "widget"),
            capabilities=capabilities,
        )

    public_routing = decision_state.execution_decision.to_public_routing() if decision_state.execution_decision else None
    actual = {
        "workflow": str((public_routing.workflow if public_routing else "") or ""),
        "execution_mode": str((public_routing.execution_mode if public_routing else "") or ""),
        "needs_products": bool(public_routing.needs_products) if public_routing else False,
        "needs_knowledge": bool(public_routing.needs_knowledge) if public_routing else False,
        "needs_clarification": bool(public_routing.needs_clarification) if public_routing else False,
        "store_overview_request": bool(public_routing.store_overview_request) if public_routing else False,
        "knowledge_query": str(decision_state.knowledge_query or ""),
        "reason": str((public_routing.reason if public_routing else "") or ""),
        "confidence": float((public_routing.confidence if public_routing else 0.0) or 0.0),
        "selection_source": str((public_routing.selection_source if public_routing else "") or ""),
        "internal_workflow": str(decision_state.internal_workflow or ""),
        "workflow_hypothesis": str(understanding.workflow_hypothesis or ""),
        "understanding_source": str(understanding.debug.get("understanding_source") or ""),
        "llm_call_count": int(understanding.llm_call_count or 0),
        "failure_reason": str(understanding.failure_reason or ""),
        "tool_suitable": bool(
            decision_state.execution_decision.tool_suitable if decision_state.execution_decision else False
        ),
        "feature_enabled": bool(
            decision_state.execution_decision.feature_enabled if decision_state.execution_decision else False
        ),
        "channel_allowed": bool(
            decision_state.execution_decision.channel_allowed if decision_state.execution_decision else False
        ),
        "token_usage_estimate": token_usage_estimate,
    }
    return _build_result(name=name, kind="routing_decision", actual=actual, expected=expected)


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


def _empty_token_usage_estimate() -> Dict[str, Any]:
    return {
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "by_call": [],
    }


def _record_estimated_token_usage(
    token_usage: Dict[str, Any],
    *,
    kind: str,
    messages: List[Dict[str, Any]],
    payload: Any,
) -> None:
    prompt_text = "\n".join(
        str(message.get("content") or "").strip()
        for message in list(messages or [])
        if isinstance(message, dict)
    ).strip()
    prompt_tokens = runtime_metrics.estimated_tokens(prompt_text)
    prompt_tokens += max(0, len(list(messages or [])) * 6)
    completion_tokens = 0
    if payload is not None:
        completion_text = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        completion_tokens = runtime_metrics.estimated_tokens(completion_text)
    total_tokens = int(prompt_tokens + completion_tokens)
    token_usage.setdefault("by_call", []).append(
        {
            "kind": kind,
            "model": "mock",
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "total_tokens": total_tokens,
            "estimated": True,
        }
    )
    token_usage["total_prompt_tokens"] = int(token_usage.get("total_prompt_tokens", 0) or 0) + int(prompt_tokens)
    token_usage["total_completion_tokens"] = int(token_usage.get("total_completion_tokens", 0) or 0) + int(completion_tokens)
    token_usage["total_tokens"] = int(token_usage.get("total_tokens", 0) or 0) + total_tokens


def _summarize_token_usage(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = _empty_token_usage_estimate()
    for result in list(results or []):
        token_usage = dict((result or {}).get("actual", {}).get("token_usage_estimate") or {})
        summary["total_prompt_tokens"] += int(token_usage.get("total_prompt_tokens", 0) or 0)
        summary["total_completion_tokens"] += int(token_usage.get("total_completion_tokens", 0) or 0)
        summary["total_tokens"] += int(token_usage.get("total_tokens", 0) or 0)
        summary["by_call"].extend(list(token_usage.get("by_call") or []))
    return summary


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
