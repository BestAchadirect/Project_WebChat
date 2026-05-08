from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.schemas.chat import ChatRequest
from app.services.chat.service import ChatService


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CASE_PATH = BACKEND_DIR / "tests" / "regression" / "data" / "chat_customer_message_coverage_cases.json"
DEFAULT_OUTPUT_PATH = BACKEND_DIR / "tmp" / "chat_customer_message_coverage_results.json"


def _load_cases(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        cases = list(payload.get("cases") or [])
    elif isinstance(payload, list):
        cases = list(payload or [])
    else:
        raise ValueError("coverage dataset must be a JSON object with cases or a JSON array")
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in cases:
        case = dict(raw or {})
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            raise ValueError("coverage case missing id")
        if case_id in seen:
            raise ValueError(f"duplicate coverage case id: {case_id}")
        if not str(case.get("message") or "").strip() and not list(case.get("turns") or []):
            raise ValueError(f"coverage case {case_id!r} needs message or turns")
        seen.add(case_id)
        out.append(case)
    return out


def _filter_cases(
    cases: Iterable[Dict[str, Any]],
    *,
    groups: set[str],
    case_ids: set[str],
    limit: int,
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for case in cases:
        group = str(case.get("group") or "ungrouped").strip().lower()
        case_id = str(case.get("id") or "").strip()
        if groups and group not in groups:
            continue
        if case_ids and case_id not in case_ids:
            continue
        selected.append(case)
        if limit > 0 and len(selected) >= limit:
            break
    return selected


def _component_types(payload: Dict[str, Any]) -> List[str]:
    return [
        str(component.get("type") or "").strip()
        for component in list(payload.get("components") or [])
        if str(component.get("type") or "").strip()
    ]


def _assistant_text(payload: Dict[str, Any]) -> str:
    for component in list(payload.get("components") or []):
        if str(component.get("type") or "").strip() != "assistant_message":
            continue
        data = dict(component.get("data") or {})
        if str(data.get("placement") or "").strip():
            continue
        text = str(data.get("text") or "").strip()
        if text:
            return text
    return ""


def _sources(payload: Dict[str, Any]) -> List[str]:
    return [
        str(source.get("title") or source.get("source_id") or "").strip()
        for source in list(payload.get("sources") or [])
        if str(source.get("title") or source.get("source_id") or "").strip()
    ]


def _issue_flags(
    *,
    expected_workflows: List[str],
    expected_needs_clarification: Any,
    expected_allow_no_products: bool,
    response_payload: Dict[str, Any],
) -> List[str]:
    routing = dict(response_payload.get("routing") or {})
    meta = dict(response_payload.get("meta") or {})
    actual_workflow = str(routing.get("workflow") or "").strip()
    needs_clarification = bool(routing.get("needs_clarification", False))
    product_display_count = int(meta.get("product_display_count") or 0)
    source_count = len(list(response_payload.get("sources") or []))
    issues: List[str] = []
    expected = [str(item or "").strip() for item in list(expected_workflows or []) if str(item or "").strip()]
    if expected and actual_workflow not in expected:
        issues.append(f"workflow_mismatch:{'/'.join(expected)}->{actual_workflow}")
    if expected_needs_clarification is not None and needs_clarification != bool(expected_needs_clarification):
        issues.append(f"clarification_mismatch:{bool(expected_needs_clarification)}->{needs_clarification}")
    if actual_workflow != "catalog" and product_display_count > 0:
        issues.append("non_catalog_returned_products")
    if actual_workflow == "knowledge" and not needs_clarification and source_count <= 0:
        issues.append("knowledge_without_sources")
    if (
        actual_workflow == "catalog"
        and not needs_clarification
        and product_display_count <= 0
        and not bool(expected_allow_no_products)
    ):
        issues.append("catalog_without_products")
    return issues


async def _run_turn(
    *,
    db: Any,
    case_id: str,
    group: str,
    message: str,
    locale: str,
    expected_workflows: List[str],
    expected_needs_clarification: Any,
    expected_allow_no_products: bool,
    conversation_id: int | None,
    turn_index: int,
) -> Dict[str, Any]:
    started = time.perf_counter()
    service = ChatService(db)
    request = ChatRequest(
        user_id=f"coverage-{case_id}",
        conversation_id=conversation_id,
        message=message,
        locale=locale,
    )
    response = await service.process_chat(request, channel="widget")
    payload = response.model_dump(mode="json")
    routing = dict(payload.get("routing") or {})
    meta = dict(payload.get("meta") or {})
    issues = _issue_flags(
        expected_workflows=expected_workflows,
        expected_needs_clarification=expected_needs_clarification,
        expected_allow_no_products=expected_allow_no_products,
        response_payload=payload,
    )
    return {
        "case_id": case_id,
        "group": group,
        "turn_index": turn_index,
        "message": message,
        "locale": locale,
        "conversation_id": payload.get("conversation_id"),
        "expected_workflow": expected_workflows[0] if len(expected_workflows) == 1 else "",
        "expected_workflows": list(expected_workflows),
        "expected_needs_clarification": expected_needs_clarification,
        "expected_allow_no_products": bool(expected_allow_no_products),
        "workflow": str(routing.get("workflow") or ""),
        "needs_clarification": bool(routing.get("needs_clarification", False)),
        "reason": str(routing.get("reason") or ""),
        "confidence": float(routing.get("confidence") or 0.0),
        "selection_source": str(routing.get("selection_source") or ""),
        "component_types": _component_types(payload),
        "assistant_text": _assistant_text(payload),
        "source_titles": _sources(payload),
        "meta": {
            "source": str(meta.get("source") or ""),
            "llm_calls": int(meta.get("llm_calls") or 0),
            "embedding_calls": int(meta.get("embedding_calls") or 0),
            "product_result_count": int(meta.get("product_result_count") or 0),
            "product_display_count": int(meta.get("product_display_count") or 0),
            "product_has_more": bool(meta.get("product_has_more", False)),
            "latency_ms": float(meta.get("latency_ms") or 0.0),
        },
        "runner_latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "issues": issues,
    }


async def run_cases(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        for case in cases:
            case_id = str(case.get("id") or "").strip()
            group = str(case.get("group") or "ungrouped").strip()
            locale = str(case.get("locale") or "en-US").strip() or "en-US"
            turns = list(case.get("turns") or [])
            conversation_id: int | None = None
            if turns:
                for index, raw_turn in enumerate(turns, start=1):
                    turn = dict(raw_turn or {})
                    turn_expected_workflows = [
                        str(item or "").strip()
                        for item in list(turn.get("expected_workflows") or case.get("expected_workflows") or [])
                        if str(item or "").strip()
                    ]
                    if not turn_expected_workflows:
                        expected_workflow = str(
                            turn.get("expected_workflow") or case.get("expected_workflow") or ""
                        ).strip()
                        turn_expected_workflows = [expected_workflow] if expected_workflow else []
                    result = await _run_turn(
                        db=db,
                        case_id=case_id,
                        group=group,
                        message=str(turn.get("message") or "").strip(),
                        locale=str(turn.get("locale") or locale),
                        expected_workflows=turn_expected_workflows,
                        expected_needs_clarification=turn.get(
                            "expected_needs_clarification",
                            case.get("expected_needs_clarification"),
                        ),
                        expected_allow_no_products=bool(
                            turn.get("expected_allow_no_products", case.get("expected_allow_no_products", False))
                        ),
                        conversation_id=conversation_id,
                        turn_index=index,
                    )
                    conversation_id = int(result.get("conversation_id") or 0) or conversation_id
                    results.append(result)
                continue
            case_expected_workflows = [
                str(item or "").strip()
                for item in list(case.get("expected_workflows") or [])
                if str(item or "").strip()
            ]
            if not case_expected_workflows:
                expected_workflow = str(case.get("expected_workflow") or "").strip()
                case_expected_workflows = [expected_workflow] if expected_workflow else []
            result = await _run_turn(
                db=db,
                case_id=case_id,
                group=group,
                message=str(case.get("message") or "").strip(),
                locale=locale,
                expected_workflows=case_expected_workflows,
                expected_needs_clarification=case.get("expected_needs_clarification"),
                expected_allow_no_products=bool(case.get("expected_allow_no_products", False)),
                conversation_id=None,
                turn_index=1,
            )
            results.append(result)

    issue_counts = Counter(issue for result in results for issue in list(result.get("issues") or []))
    by_group: Dict[str, Dict[str, Any]] = {}
    grouped_results: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped_results[str(result.get("group") or "ungrouped")].append(result)
    for group, group_results in sorted(grouped_results.items()):
        by_group[group] = {
            "turns": len(group_results),
            "workflows": dict(Counter(str(item.get("workflow") or "unknown") for item in group_results)),
            "issues": dict(Counter(issue for item in group_results for issue in list(item.get("issues") or []))),
        }
    return {
        "summary": {
            "cases": len(cases),
            "turns": len(results),
            "workflows": dict(Counter(str(item.get("workflow") or "unknown") for item in results)),
            "issues": dict(issue_counts),
            "issue_turn_count": sum(1 for result in results if result.get("issues")),
            "by_group": by_group,
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run broad live customer-message chatbot coverage.")
    parser.add_argument("--cases", default=str(DEFAULT_CASE_PATH), help="Coverage case JSON path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output JSON report path.")
    parser.add_argument("--group", action="append", default=[], help="Only run a group. Can be repeated.")
    parser.add_argument("--case-id", action="append", default=[], help="Only run a case id. Can be repeated.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of cases after filtering.")
    args = parser.parse_args()

    cases = _filter_cases(
        _load_cases(Path(args.cases)),
        groups={str(item).strip().lower() for item in args.group if str(item).strip()},
        case_ids={str(item).strip() for item in args.case_id if str(item).strip()},
        limit=int(args.limit or 0),
    )
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    report = asyncio.run(run_cases(cases))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=True))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
