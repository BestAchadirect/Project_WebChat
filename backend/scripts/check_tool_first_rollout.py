from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_CHANNELS = ("widget", "qa_console")
DEFAULT_MINIMUM_SELECTED = 100
FALLBACK_YELLOW_RATE = 0.10
FALLBACK_RED_RATE = 0.20
EXPECTED_TOOL_YELLOW_RATE = 0.02
EXPECTED_TOOL_RED_RATE = 0.05
GROUNDING_YELLOW_RATE = 0.02
GROUNDING_RED_RATE = 0.05
STATUS_SPIKE_KEYS = {"failed", "no_answer", "no-answer"}


@dataclass(frozen=True)
class RolloutAssessment:
    channel: str
    status: str
    tool_first_selected: int
    fallback_to_component_rate: float
    expected_tool_missing_rate: float
    grounding_failed_rate: float
    failed_or_no_answer_rows: int
    reasons: list[str]
    top_tools: list[dict[str, Any]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rate(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _status_spike_count(summary: dict[str, Any]) -> int:
    raw_summary = summary.get("raw_summary")
    if not isinstance(raw_summary, dict):
        raw_summary = {}
    by_status = raw_summary.get("by_status")
    if not isinstance(by_status, dict):
        by_status = summary.get("by_status")
    if not isinstance(by_status, dict):
        return 0

    total = 0
    for status, count in by_status.items():
        normalized = str(status or "").strip().lower()
        if normalized in STATUS_SPIKE_KEYS:
            total += _count(count)
    return total


def assess_tool_first_summary(
    channel: str,
    payload: dict[str, Any],
    *,
    minimum_selected: int = DEFAULT_MINIMUM_SELECTED,
) -> RolloutAssessment:
    summary = payload.get("toolFirst") if "toolFirst" in payload else payload
    if not isinstance(summary, dict):
        summary = {}

    selected = _count(summary.get("tool_first_selected"))
    fallback_rate = _rate(summary.get("fallback_to_component_rate"))
    expected_tool_rate = _rate(summary.get("expected_tool_missing_rate"))
    grounding_rate = _rate(summary.get("grounding_failed_rate"))
    failed_or_no_answer = _status_spike_count(summary)

    red_reasons: list[str] = []
    yellow_reasons: list[str] = []
    notes: list[str] = []

    if selected < minimum_selected:
        notes.append(f"insufficient_sample: selected={selected}, minimum={minimum_selected}")

    if fallback_rate > FALLBACK_RED_RATE:
        red_reasons.append(f"fallback_to_component_rate={fallback_rate:.4f} > {FALLBACK_RED_RATE:.2f}")
    elif fallback_rate >= FALLBACK_YELLOW_RATE:
        yellow_reasons.append(f"fallback_to_component_rate={fallback_rate:.4f} >= {FALLBACK_YELLOW_RATE:.2f}")

    if expected_tool_rate > EXPECTED_TOOL_RED_RATE:
        red_reasons.append(f"expected_tool_missing_rate={expected_tool_rate:.4f} > {EXPECTED_TOOL_RED_RATE:.2f}")
    elif expected_tool_rate >= EXPECTED_TOOL_YELLOW_RATE:
        yellow_reasons.append(f"expected_tool_missing_rate={expected_tool_rate:.4f} >= {EXPECTED_TOOL_YELLOW_RATE:.2f}")

    if grounding_rate > GROUNDING_RED_RATE:
        red_reasons.append(f"grounding_failed_rate={grounding_rate:.4f} > {GROUNDING_RED_RATE:.2f}")
    elif grounding_rate >= GROUNDING_YELLOW_RATE:
        yellow_reasons.append(f"grounding_failed_rate={grounding_rate:.4f} >= {GROUNDING_YELLOW_RATE:.2f}")

    if failed_or_no_answer > 0:
        red_reasons.append(f"failed_or_no_answer_rows={failed_or_no_answer}")

    if red_reasons:
        status = "red"
        reasons = red_reasons + yellow_reasons + notes
    elif yellow_reasons:
        status = "yellow"
        reasons = yellow_reasons + notes
    elif notes:
        status = "insufficient_sample"
        reasons = notes
    else:
        status = "green"
        reasons = []

    top_tools = summary.get("top_tools")
    if not isinstance(top_tools, list):
        top_tools = []

    return RolloutAssessment(
        channel=channel,
        status=status,
        tool_first_selected=selected,
        fallback_to_component_rate=fallback_rate,
        expected_tool_missing_rate=expected_tool_rate,
        grounding_failed_rate=grounding_rate,
        failed_or_no_answer_rows=failed_or_no_answer,
        reasons=reasons,
        top_tools=top_tools,
        summary=summary,
    )


def exit_code_for_assessments(assessments: list[RolloutAssessment]) -> int:
    if any(assessment.status == "red" for assessment in assessments):
        return 1
    if any(assessment.status in {"yellow", "insufficient_sample"} for assessment in assessments):
        return 2
    return 0


def _parse_headers(raw_headers: list[str]) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = os.getenv("QA_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for raw_header in raw_headers:
        if "=" not in raw_header:
            raise ValueError(f"Invalid header {raw_header!r}. Expected NAME=VALUE.")
        name, value = raw_header.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"Invalid header {raw_header!r}. Header name is empty.")
        headers[name] = value.strip()
    return headers


def fetch_rollout_summary(
    *,
    base_url: str,
    qa_prefix: str,
    channel: str,
    max_rows: int,
    timeout_seconds: float,
    headers: dict[str, str],
    created_from: str | None = None,
    created_to: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"channel": channel, "maxRows": max_rows}
    if created_from:
        params["createdFrom"] = created_from
    if created_to:
        params["createdTo"] = created_to
    normalized_prefix = "/" + str(qa_prefix or "").strip("/")
    url = (
        f"{base_url.rstrip('/')}{normalized_prefix}/qa-logs/rollout-summary?"
        f"{urlencode(params)}"
    )
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object response from {url}")
    return payload


def _print_assessment(assessment: RolloutAssessment) -> None:
    print(
        " | ".join(
            [
                f"{assessment.channel}: {assessment.status.upper()}",
                f"selected={assessment.tool_first_selected}",
                f"fallback={assessment.fallback_to_component_rate:.2%}",
                f"expected_tool_missing={assessment.expected_tool_missing_rate:.2%}",
                f"grounding_failed={assessment.grounding_failed_rate:.2%}",
                f"failed_or_no_answer={assessment.failed_or_no_answer_rows}",
            ]
        )
    )
    if assessment.top_tools:
        print(f"  top_tools={assessment.top_tools}")
    for reason in assessment.reasons:
        print(f"  reason: {reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate tool-first chat rollout health.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend API base URL.")
    parser.add_argument(
        "--qa-prefix",
        default="/api/v1/dashboard/qa",
        help="Mounted QA route prefix.",
    )
    parser.add_argument(
        "--channels",
        nargs="+",
        default=list(DEFAULT_CHANNELS),
        help="Channels to validate.",
    )
    parser.add_argument("--created-from", default=None, help="Optional ISO createdFrom filter.")
    parser.add_argument("--created-to", default=None, help="Optional ISO createdTo filter.")
    parser.add_argument("--max-rows", type=int, default=5000, help="rollout-summary maxRows.")
    parser.add_argument(
        "--minimum-selected",
        type=int,
        default=DEFAULT_MINIMUM_SELECTED,
        help="Minimum tool-first selected rows per channel.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=15.0, help="HTTP request timeout.")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Additional HTTP header as NAME=VALUE. QA_API_TOKEN also sets Authorization.",
    )
    parser.add_argument("--output-json", default="", help="Optional path to write full assessment JSON.")
    args = parser.parse_args(argv)

    try:
        headers = _parse_headers(list(args.header or []))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    assessments: list[RolloutAssessment] = []
    for channel in args.channels:
        channel_value = str(channel or "").strip()
        if not channel_value:
            continue
        try:
            payload = fetch_rollout_summary(
                base_url=str(args.base_url),
                qa_prefix=str(args.qa_prefix),
                channel=channel_value,
                max_rows=max(1, int(args.max_rows or 5000)),
                timeout_seconds=max(1.0, float(args.timeout_seconds or 15.0)),
                headers=headers,
                created_from=args.created_from,
                created_to=args.created_to,
            )
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"{channel_value}: HTTP {exc.code} from rollout-summary: {body}", file=sys.stderr)
            return 2
        except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            print(f"{channel_value}: failed to fetch rollout-summary: {exc}", file=sys.stderr)
            return 2
        assessments.append(
            assess_tool_first_summary(
                channel_value,
                payload,
                minimum_selected=max(1, int(args.minimum_selected or DEFAULT_MINIMUM_SELECTED)),
            )
        )

    for assessment in assessments:
        _print_assessment(assessment)

    report = {
        "base_url": args.base_url,
        "channels": [assessment.to_dict() for assessment in assessments],
        "exit_code": exit_code_for_assessments(assessments),
    }
    if args.output_json:
        output_path = Path(args.output_json).expanduser().resolve()
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"Wrote report to: {output_path}")

    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
