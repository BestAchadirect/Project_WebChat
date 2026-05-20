from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

DEFAULT_CHANNELS = ("widget", "qa_console")
DEFAULT_CASES = (
    {
        "id": "return_policy",
        "message": "What is your return policy?",
        "workflow": "knowledge",
        "tool": "search_knowledge_base",
    },
    {
        "id": "shipping_policy",
        "message": "What is your shipping policy?",
        "workflow": "knowledge",
        "tool": "search_knowledge_base",
    },
    {
        "id": "black_opal_labrets",
        "message": "Do you guys have any black opal labrets?",
        "workflow": "catalog",
        "tool": "search_products",
    },
    {
        "id": "titanium_labrets",
        "message": "Show me titanium labrets",
        "workflow": "catalog",
        "tool": "search_products",
    },
)
PASS_GROUNDING_STATUSES = {"grounded"}


@dataclass(frozen=True)
class SmokeCase:
    id: str
    message: str
    expected_workflow: str
    expected_tool: str


@dataclass(frozen=True)
class ToolEvent:
    tool: str
    status: str
    result_count: int | None
    args: dict[str, Any]


@dataclass(frozen=True)
class SmokeResult:
    channel: str
    case_id: str
    message: str
    workflow: str
    workflow_path: str
    agentic_selected: bool
    fallback_reason: str
    grounding_status: str
    grounding_action: str
    product_count: int
    source_count: int
    tools: list[ToolEvent]
    issues: list[str]
    qa_log_id: str
    conversation_id: str
    latency_ms: float

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    logging.getLogger().handlers = []
    logging.basicConfig(level=logging.WARNING)
    for logger_name in logging.Logger.manager.loggerDict:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _extract_tool_events(agentic_debug: dict[str, Any]) -> list[ToolEvent]:
    events: list[ToolEvent] = []
    for raw_event in list(agentic_debug.get("trace") or []):
        event = _as_dict(raw_event)
        tool = str(event.get("tool") or event.get("name") or "").strip()
        if not tool:
            continue
        raw_count = event.get("result_count")
        try:
            result_count = int(raw_count) if raw_count is not None else None
        except (TypeError, ValueError):
            result_count = None
        events.append(
            ToolEvent(
                tool=tool,
                status=str(event.get("tool_status") or event.get("status") or "").strip(),
                result_count=result_count,
                args=_as_dict(event.get("args")),
            )
        )
    return events


def _extract_grounding(agentic_debug: dict[str, Any], harness_trace: dict[str, Any]) -> tuple[str, str]:
    grounding = _as_dict(agentic_debug.get("grounding"))
    status = str(grounding.get("status") or harness_trace.get("grounding_status") or "").strip()
    action = str(grounding.get("safe_customer_action") or "").strip()

    for key in ("catalog", "knowledge"):
        nested = _as_dict(grounding.get(key))
        if not status:
            status = str(nested.get("status") or "").strip()
        if not action:
            action = str(nested.get("safe_customer_action") or "").strip()

    return status, action


def _response_count(response: Any, attr_name: str, meta_key: str) -> int:
    raw_items = getattr(response, attr_name, None)
    if raw_items is not None:
        try:
            return len(list(raw_items or []))
        except TypeError:
            pass
    meta = getattr(response, "meta", None)
    if isinstance(meta, dict):
        raw_count = meta.get(meta_key)
    else:
        raw_count = getattr(meta, meta_key, 0)
    try:
        return int(raw_count or 0)
    except (TypeError, ValueError):
        return 0


def summarize_response(
    *,
    channel: str,
    case: SmokeCase,
    response: Any,
    latency_ms: float,
) -> SmokeResult:
    debug = _as_dict(getattr(response, "debug", None))
    routing = getattr(response, "routing", None)
    agentic = _as_dict(debug.get("agentic"))
    harness_trace = _as_dict(debug.get("harness_trace"))
    tools = _extract_tool_events(agentic)
    grounding_status, grounding_action = _extract_grounding(agentic, harness_trace)

    workflow = str(
        debug.get("workflow")
        or getattr(routing, "workflow", "")
        or harness_trace.get("route")
        or ""
    ).strip()
    workflow_path = str(debug.get("workflow_path") or harness_trace.get("execution_mode") or "").strip()
    fallback_reason = str(agentic.get("fallback_reason") or harness_trace.get("fallback_reason") or "").strip()
    selected = bool(agentic.get("selected") or harness_trace.get("execution_mode") == "agentic")

    issues = result_issues(
        expected_workflow=case.expected_workflow,
        expected_tool=case.expected_tool,
        workflow=workflow,
        agentic_selected=selected,
        fallback_reason=fallback_reason,
        grounding_status=grounding_status,
        tools=tools,
    )

    return SmokeResult(
        channel=channel,
        case_id=case.id,
        message=case.message,
        workflow=workflow,
        workflow_path=workflow_path,
        agentic_selected=selected,
        fallback_reason=fallback_reason,
        grounding_status=grounding_status,
        grounding_action=grounding_action,
        product_count=_response_count(response, "product_carousel", "product_display_count"),
        source_count=_response_count(response, "sources", "source_count"),
        tools=tools,
        issues=issues,
        qa_log_id=str(getattr(response, "qa_log_id", "") or ""),
        conversation_id=str(getattr(response, "conversation_id", "") or ""),
        latency_ms=round(float(latency_ms or 0.0), 2),
    )


def result_issues(
    *,
    expected_workflow: str,
    expected_tool: str,
    workflow: str,
    agentic_selected: bool,
    fallback_reason: str,
    grounding_status: str,
    tools: list[ToolEvent],
) -> list[str]:
    issues: list[str] = []
    if workflow != expected_workflow:
        issues.append(f"workflow_mismatch:{expected_workflow}->{workflow or 'missing'}")
    if not agentic_selected:
        issues.append("agentic_not_selected")
    if fallback_reason:
        issues.append(f"fallback:{fallback_reason}")
    tool_names = {event.tool for event in tools}
    if not tool_names:
        issues.append("no_tool_call")
    elif expected_tool not in tool_names:
        issues.append(f"expected_tool_missing:{expected_tool}")
    if grounding_status not in PASS_GROUNDING_STATUSES:
        issues.append(f"grounding_not_grounded:{grounding_status or 'missing'}")
    return issues


def load_cases(case_ids: set[str] | None = None) -> list[SmokeCase]:
    selected: list[SmokeCase] = []
    for raw_case in DEFAULT_CASES:
        case = SmokeCase(
            id=str(raw_case["id"]),
            message=str(raw_case["message"]),
            expected_workflow=str(raw_case["workflow"]),
            expected_tool=str(raw_case["tool"]),
        )
        if case_ids and case.id not in case_ids:
            continue
        selected.append(case)
    return selected


async def run_smoke(
    *,
    channels: list[str],
    cases: list[SmokeCase],
    repeat: int,
    user_prefix: str,
    locale: str,
) -> list[SmokeResult]:
    from app.db.session import AsyncSessionLocal
    from app.schemas.chat import ChatRequest
    from app.services.chat.service import ChatService

    results: list[SmokeResult] = []
    run_token = str(int(time.time()))
    for channel in channels:
        for iteration in range(1, max(1, repeat) + 1):
            for case in cases:
                async with AsyncSessionLocal() as db:
                    service = ChatService(db)
                    request = ChatRequest(
                        user_id=f"{user_prefix}-{run_token}-{channel}-{iteration}-{case.id}",
                        message=case.message,
                        locale=locale,
                    )
                    started = time.perf_counter()
                    response = await service.process_chat(request, channel=channel)
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    results.append(
                        summarize_response(
                            channel=channel,
                            case=case,
                            response=response,
                            latency_ms=latency_ms,
                        )
                    )
    return results


def print_results(results: list[SmokeResult]) -> None:
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        tools = [
            f"{event.tool}:{event.status or 'unknown'}:{event.result_count if event.result_count is not None else '-'}"
            for event in result.tools
        ]
        print(
            " | ".join(
                [
                    status,
                    f"channel={result.channel}",
                    f"case={result.case_id}",
                    f"workflow={result.workflow or '-'}",
                    f"path={result.workflow_path or '-'}",
                    f"selected={result.agentic_selected}",
                    f"fallback={result.fallback_reason or '-'}",
                    f"grounding={result.grounding_status or '-'}"
                    f"/{result.grounding_action or '-'}",
                    f"products={result.product_count}",
                    f"sources={result.source_count}",
                    f"tools={tools}",
                    f"issues={result.issues}",
                    f"latency_ms={result.latency_ms:.2f}",
                ]
            )
        )


def _write_json(path: str, *, created_from: str, results: list[SmokeResult]) -> None:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_from": created_from,
        "total": len(results),
        "passed": sum(1 for result in results if result.passed),
        "failed": sum(1 for result in results if not result.passed),
        "results": [result.to_dict() for result in results],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote smoke report to: {output_path}")


def rollout_minimum_selected(results: list[SmokeResult]) -> int:
    counts = Counter(str(result.channel or "").strip() for result in results if str(result.channel or "").strip())
    if not counts:
        return 1
    return max(1, min(counts.values()))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate tool-first chat smoke traffic.")
    parser.add_argument(
        "--channels",
        nargs="+",
        default=list(DEFAULT_CHANNELS),
        help="Channels to exercise.",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Case id to run. Can be supplied multiple times. Defaults to all smoke cases.",
    )
    parser.add_argument("--repeat", type=int, default=1, help="Repeat each case per channel.")
    parser.add_argument("--locale", default="en-US", help="Chat request locale.")
    parser.add_argument("--user-prefix", default="tool-first-smoke", help="Generated user id prefix.")
    parser.add_argument("--output-json", default="", help="Optional path for a JSON smoke report.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    args = parse_args(argv)
    channels = [str(channel or "").strip() for channel in list(args.channels or []) if str(channel or "").strip()]
    case_ids = {str(case_id or "").strip() for case_id in list(args.case or []) if str(case_id or "").strip()}
    cases = load_cases(case_ids or None)
    if not channels:
        print("No channels selected.", file=sys.stderr)
        return 2
    if not cases:
        print(f"No smoke cases matched: {sorted(case_ids)}", file=sys.stderr)
        return 2

    created_from = _utc_timestamp()
    print(f"created_from={created_from}")
    results = asyncio.run(
        run_smoke(
            channels=channels,
            cases=cases,
            repeat=max(1, int(args.repeat or 1)),
            user_prefix=str(args.user_prefix or "tool-first-smoke"),
            locale=str(args.locale or "en-US"),
        )
    )
    print_results(results)
    if args.output_json:
        _write_json(str(args.output_json), created_from=created_from, results=results)

    failed = [result for result in results if not result.passed]
    if failed:
        print(f"Smoke failed: {len(failed)} of {len(results)} case(s) failed.", file=sys.stderr)
        return 1
    print(f"Smoke passed: {len(results)} case(s).")
    print(
        "Rollout check example: "
        ".\\venv\\Scripts\\python.exe scripts\\check_tool_first_rollout.py "
        f"--base-url http://localhost:8000 --channels {' '.join(channels)} "
        f"--created-from {created_from} --minimum-selected {rollout_minimum_selected(results)}"
    )
    return 0


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(main())
