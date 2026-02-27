from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.db.session import AsyncSessionLocal
from app.schemas.chat import ChatRequest, ProductCard
from app.services.chat.service import ChatService


def _flatten_cases(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for category in payload.get("categories", []) or []:
        category_name = str(category.get("category") or "").strip()
        for case in category.get("test_cases", []) or []:
            record = dict(case)
            record["_category"] = category_name
            rows.append(record)
    return rows


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _contains_ci(haystack: str, needle: str) -> bool:
    return _norm_text(needle) in _norm_text(haystack)


def _is_product_like_intent(expected_intent: str) -> bool:
    intent = _norm_text(expected_intent)
    return intent.startswith("product_") or intent in {
        "minimum_order",
        "bulk_discount",
    }


def _expected_runtime_intents(case: Dict[str, Any]) -> set[str]:
    expected = _norm_text(case.get("expected_intent"))
    user_input = _norm_text(case.get("user_input"))

    # Runtime intent labels are intentionally coarse compared to FAQ labels.
    if expected in {"empty_input", "out_of_scope"}:
        return {"off_topic", "fallback_general"}

    if _is_product_like_intent(expected):
        if "sku" in user_input or str(case.get("expected_sku") or "").strip():
            return {"search_specific", "detail_mode", "rag_strict"}
        return {"browse_products", "search_specific", "detail_mode", "rag_strict"}

    return {"knowledge_query", "rag_strict"}


def _build_response_text(response: Any) -> str:
    parts: List[str] = []
    parts.append(str(getattr(response, "reply_text", "") or ""))
    parts.append(str(getattr(response, "carousel_msg", "") or ""))
    parts.extend([str(q or "") for q in list(getattr(response, "follow_up_questions", []) or [])])
    return "\n".join([p for p in parts if p])


def _find_card_by_sku(cards: List[ProductCard], sku: str) -> Optional[ProductCard]:
    want = _norm_text(sku)
    if not want:
        return None
    for card in cards:
        if _norm_text(getattr(card, "sku", "")) == want:
            return card
    return None


def _truthy_or_none(values: List[Optional[bool]]) -> Optional[bool]:
    concrete = [v for v in values if v is not None]
    if not concrete:
        return None
    return all(concrete)


def _case_result(
    *,
    case: Dict[str, Any],
    response: Any,
    elapsed_ms: float,
) -> Dict[str, Any]:
    debug = dict(getattr(response, "debug", {}) or {})
    response_text = _build_response_text(response)
    actual_intent = str(getattr(response, "intent", "") or "")
    expected_intents = _expected_runtime_intents(case)
    intent_pass = actual_intent in expected_intents

    expected_contains = str(case.get("expected_response_contains") or "").strip()
    contains_pass: Optional[bool] = None
    if expected_contains:
        contains_pass = _contains_ci(response_text, expected_contains)

    expected_keywords = [str(k).strip() for k in list(case.get("expected_keywords") or []) if str(k).strip()]
    keywords_pass: Optional[bool] = None
    missing_keywords: List[str] = []
    if expected_keywords:
        checks = []
        for keyword in expected_keywords:
            ok = _contains_ci(response_text, keyword)
            checks.append(ok)
            if not ok:
                missing_keywords.append(keyword)
        keywords_pass = all(checks)

    cards = list(getattr(response, "product_carousel", []) or [])
    expected_sku = str(case.get("expected_sku") or case.get("expected_sample_sku") or "").strip()
    sku_pass: Optional[bool] = None
    stock_pass: Optional[bool] = None
    price_pass: Optional[bool] = None
    matched_card: Optional[ProductCard] = None
    if expected_sku:
        matched_card = _find_card_by_sku(cards, expected_sku)
        sku_pass = matched_card is not None

    expected_stock = str(case.get("expected_stock_status") or "").strip()
    if expected_stock:
        if matched_card is None:
            stock_pass = False
        else:
            stock_pass = _norm_text(getattr(matched_card, "stock_status", "")) == _norm_text(expected_stock)

    expected_price = case.get("expected_price_usd")
    if expected_price is not None:
        if matched_card is None:
            price_pass = False
        else:
            try:
                actual_price = float(getattr(matched_card, "price"))
                price_pass = abs(actual_price - float(expected_price)) < 0.01
            except Exception:
                price_pass = False

    pass_checks = [intent_pass, contains_pass, keywords_pass, sku_pass, stock_pass, price_pass]
    case_pass = _truthy_or_none(pass_checks)

    network_error_type = str(debug.get("network_error_type") or "").strip()
    blocked_by_network = bool(network_error_type)

    latency_spans = dict(debug.get("latency_spans", {}) or {})
    total_ms = latency_spans.get("total_ms")
    if total_ms is None:
        total_ms = round(float(elapsed_ms), 2)

    return {
        "id": case.get("id"),
        "category": case.get("_category"),
        "priority": case.get("priority"),
        "user_input": case.get("user_input"),
        "expected_intent": case.get("expected_intent"),
        "accepted_runtime_intents": sorted(expected_intents),
        "actual_intent": actual_intent,
        "checks": {
            "intent_pass": intent_pass,
            "contains_pass": contains_pass,
            "keywords_pass": keywords_pass,
            "sku_pass": sku_pass,
            "stock_pass": stock_pass,
            "price_pass": price_pass,
        },
        "missing_keywords": missing_keywords,
        "expected_response_contains": expected_contains or None,
        "expected_sku": expected_sku or None,
        "actual_skus": [getattr(card, "sku", None) for card in cards],
        "blocked_by_network": blocked_by_network,
        "network_error_type": network_error_type or None,
        "external_call_budget_exceeded_reason": debug.get("external_call_budget_exceeded_reason"),
        "latency_ms": total_ms,
        "pass": bool(case_pass) if case_pass is not None else False,
        "reply_excerpt": str(getattr(response, "reply_text", "") or "")[:260],
    }


async def _run_eval(
    *,
    cases: List[Dict[str, Any]],
    user_prefix: str,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        service = ChatService(db)
        for idx, case in enumerate(cases, start=1):
            user_input = str(case.get("user_input") or "").strip()
            if not user_input:
                rows.append(
                    {
                        "id": case.get("id"),
                        "category": case.get("_category"),
                        "pass": False,
                        "blocked_by_network": False,
                        "error": "missing user_input",
                    }
                )
                continue

            started = asyncio.get_running_loop().time()
            try:
                request = ChatRequest(
                    user_id=f"{user_prefix}-{idx % 4}",
                    message=user_input,
                    locale="en-US",
                )
                response = await service.process_chat(request, channel="widget")
                elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000.0
                rows.append(_case_result(case=case, response=response, elapsed_ms=elapsed_ms))
            except Exception as exc:
                elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000.0
                try:
                    await db.rollback()
                except Exception:
                    pass
                rows.append(
                    {
                        "id": case.get("id"),
                        "category": case.get("_category"),
                        "pass": False,
                        "blocked_by_network": False,
                        "error": str(exc),
                        "latency_ms": round(float(elapsed_ms), 2),
                    }
                )

    pass_count = sum(1 for row in rows if bool(row.get("pass")))
    blocked_count = sum(1 for row in rows if bool(row.get("blocked_by_network")))
    fail_count = len(rows) - pass_count

    latencies = [float(row.get("latency_ms", 0.0) or 0.0) for row in rows if row.get("latency_ms") is not None]
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    p95_latency = 0.0
    if latencies:
        ordered = sorted(latencies)
        rank = int(math.ceil(0.95 * len(ordered))) - 1
        rank = max(0, min(len(ordered) - 1, rank))
        p95_latency = round(ordered[rank], 2)

    return {
        "summary": {
            "total_cases": len(rows),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "blocked_by_network_count": blocked_count,
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
        },
        "rows": rows,
    }


def _print_human(report: Dict[str, Any]) -> None:
    summary = dict(report.get("summary", {}) or {})
    print("FAQ JSON EVAL SUMMARY")
    print(f"- Total cases: {summary.get('total_cases', 0)}")
    print(f"- Passed: {summary.get('pass_count', 0)}")
    print(f"- Failed: {summary.get('fail_count', 0)}")
    print(f"- Blocked by network: {summary.get('blocked_by_network_count', 0)}")
    print(f"- Avg latency: {summary.get('avg_latency_ms', 0)} ms")
    print(f"- P95 latency: {summary.get('p95_latency_ms', 0)} ms")

    blocked_examples = [row for row in report.get("rows", []) if row.get("blocked_by_network")]
    if blocked_examples:
        print("")
        print("Blocked examples:")
        for row in blocked_examples[:5]:
            print(
                f"- {row.get('id')}: intent={row.get('actual_intent')} "
                f"network_error={row.get('network_error_type')}"
            )


def _filter_cases(
    *,
    cases: List[Dict[str, Any]],
    category: Optional[str],
    limit: Optional[int],
) -> List[Dict[str, Any]]:
    result = list(cases)
    if category:
        wanted = _norm_text(category)
        result = [row for row in result if _norm_text(row.get("_category")) == wanted]
    if limit is not None and limit > 0:
        result = result[:limit]
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run FAQ JSON evaluation against chat service.")
    parser.add_argument(
        "--input",
        type=str,
        default="tests/acha_chatbot_faq_test_script.json",
        help="Path to FAQ JSON file (relative to backend/).",
    )
    parser.add_argument("--category", type=str, default=None, help="Optional category filter.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of cases.")
    parser.add_argument("--user-prefix", type=str, default="faq-eval", help="User id prefix.")
    parser.add_argument("--json-out", type=str, default=None, help="Optional report output path.")
    args = parser.parse_args()

    source = Path(args.input)
    if not source.is_absolute():
        source = (BACKEND_ROOT / source).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Input JSON not found: {source}")

    payload = json.loads(source.read_text(encoding="utf-8"))
    cases = _flatten_cases(payload)
    selected = _filter_cases(cases=cases, category=args.category, limit=args.limit)
    report = await _run_eval(cases=selected, user_prefix=str(args.user_prefix))

    output: Dict[str, Any] = {
        "input_file": str(source),
        "test_suite": payload.get("test_suite"),
        "version": payload.get("version"),
        "selected_cases": len(selected),
        **report,
    }

    _print_human(output)

    if args.json_out:
        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = (BACKEND_ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=True), encoding="utf-8")
        print("")
        print(f"Saved report to: {out_path}")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
