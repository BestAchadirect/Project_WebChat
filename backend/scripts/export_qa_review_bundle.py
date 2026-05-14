import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import desc, func, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.db.session import AsyncSessionLocal
from app.models.qa_log import QALog
from app.services.chat.observability.regression_case_templates import build_review_bundle_from_qa_log


def _failure_bucket_expr() -> Any:
    return func.lower(
        func.coalesce(QALog.token_usage["chat_metrics"]["failure_bucket"].astext, "")
    )


async def _load_logs(
    *,
    qa_log_ids: List[str],
    failure_bucket: str,
    status: str,
    limit: int,
) -> List[QALog]:
    async with AsyncSessionLocal() as db:
        stmt = select(QALog)
        if qa_log_ids:
            ids = [UUID(item) for item in qa_log_ids]
            stmt = stmt.where(QALog.id.in_(ids))
        if failure_bucket:
            stmt = stmt.where(_failure_bucket_expr() == failure_bucket.strip().lower())
        if status:
            stmt = stmt.where(QALog.status == status.strip())
        stmt = stmt.order_by(desc(QALog.created_at), desc(QALog.id)).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def run(
    *,
    qa_log_ids: List[str],
    failure_bucket: str,
    status: str,
    limit: int,
) -> List[Dict[str, Any]]:
    logs = await _load_logs(
        qa_log_ids=qa_log_ids,
        failure_bucket=failure_bucket,
        status=status,
        limit=limit,
    )
    bundles: List[Dict[str, Any]] = []
    for log in logs:
        bundles.append(build_review_bundle_from_qa_log(log))
    return bundles


def main() -> int:
    parser = argparse.ArgumentParser(description="Export QA logs into reviewable regression-case bundles.")
    parser.add_argument(
        "--qa-log-id",
        dest="qa_log_ids",
        action="append",
        default=[],
        help="Specific QA log id to export. Repeat for multiple ids.",
    )
    parser.add_argument(
        "--failure-bucket",
        type=str,
        default="",
        help="Optional failure bucket filter such as hard_constraint_no_match.",
    )
    parser.add_argument(
        "--status",
        type=str,
        default="",
        help="Optional QA status filter such as success or fallback.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of bundles to export.",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="",
        help="Optional path to write the exported bundles as JSON.",
    )
    args = parser.parse_args()

    bundles = asyncio.run(
        run(
            qa_log_ids=[str(item).strip() for item in list(args.qa_log_ids or []) if str(item).strip()],
            failure_bucket=str(args.failure_bucket or "").strip(),
            status=str(args.status or "").strip(),
            limit=max(1, int(args.limit or 10)),
        )
    )

    payload = {
        "count": len(bundles),
        "bundles": bundles,
    }

    output_json = str(args.output_json or "").strip()
    if output_json:
        output_path = Path(output_json).expanduser().resolve()
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {len(bundles)} bundle(s) to {output_path}")
        return 0

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
