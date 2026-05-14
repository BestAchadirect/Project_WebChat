import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.db.session import AsyncSessionLocal
from app.models.qa_log import QALog
from app.services.chat.observability import qa_failure_analysis, qa_metrics


def _fallback_response(answer: str, token_usage: Dict[str, Any] | None) -> Any:
    metrics = qa_metrics.extract_chat_metrics(token_usage)
    return SimpleNamespace(
        reply_text=answer or "",
        debug={},
        routing=SimpleNamespace(workflow=metrics.get("workflow") or ""),
        sources=[],
    )


async def _load_rows(limit: int) -> List[QALog]:
    async with AsyncSessionLocal() as db:
        stmt = select(QALog).order_by(QALog.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def run(limit: int) -> Dict[str, Any]:
    rows = await _load_rows(limit)
    row_metrics: List[Dict[str, Any]] = []
    examples_by_bucket: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    bucket_counts: Counter[str] = Counter()

    for log in rows:
        metrics = qa_metrics.extract_chat_metrics(getattr(log, "token_usage", None))
        analysis = dict(metrics.get("failure_analysis") or {})
        if not analysis:
            analysis = qa_failure_analysis.classify_failure(
                user_text=getattr(log, "question", "") or "",
                response=_fallback_response(getattr(log, "answer", "") or "", getattr(log, "token_usage", None)),
                chat_metrics=metrics,
            ).to_dict()
        bucket = str(analysis.get("bucket") or "other").strip() or "other"
        bucket_counts[bucket] += 1
        row_metrics.append(
            {
                "id": str(getattr(log, "id", "")),
                "created_at": str(getattr(log, "created_at", "")),
                "question": getattr(log, "question", ""),
                "answer": getattr(log, "answer", ""),
                "workflow": metrics.get("workflow") or "unknown",
                "status": metrics.get("status") or str(getattr(log, "status", "")),
                "failure_analysis": analysis,
            }
        )
        if len(examples_by_bucket[bucket]) < 3:
            examples_by_bucket[bucket].append(
                {
                    "id": str(getattr(log, "id", "")),
                    "question": getattr(log, "question", ""),
                    "reason": analysis.get("reason"),
                    "suggested_action": analysis.get("suggested_action"),
                }
            )

    summary = qa_metrics.summarize_chat_metrics(
        [qa_metrics.extract_chat_metrics(getattr(log, "token_usage", None)) for log in rows]
    )
    summary["by_failure_bucket"] = dict(sorted(bucket_counts.items()))

    return {
        "summary": summary,
        "rows": row_metrics,
        "examples_by_bucket": dict(sorted(examples_by_bucket.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine recent chat QA failures.")
    parser.add_argument("--limit", type=int, default=100, help="Number of recent QA logs to inspect.")
    parser.add_argument(
        "--output-json",
        type=str,
        default="",
        help="Optional path to write the full report as JSON.",
    )
    args = parser.parse_args()

    limit = max(1, int(args.limit or 100))
    report = asyncio.run(run(limit))

    summary = report["summary"]
    print(f"Total rows: {summary.get('total_rows', 0)}")
    print(f"By failure bucket: {summary.get('by_failure_bucket', {})}")
    print(f"By workflow: {summary.get('by_workflow', {})}")
    print(f"By grounding status: {summary.get('by_grounding_status', {})}")

    examples_by_bucket = report.get("examples_by_bucket", {})
    if examples_by_bucket:
        print("\nExamples:")
        for bucket, examples in examples_by_bucket.items():
            print(f"- {bucket}:")
            for example in examples:
                print(f"  - {example['question']}")
                print(f"    reason: {example.get('reason')}")
                print(f"    action: {example.get('suggested_action')}")

    output_json = str(args.output_json or "").strip()
    if output_json:
        output_path = Path(output_json).expanduser().resolve()
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote report to: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
