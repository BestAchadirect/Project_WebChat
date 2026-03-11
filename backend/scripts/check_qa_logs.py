import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.db.session import AsyncSessionLocal
from app.models.qa_log import QALog
from app.services.chat import qa_metrics
from sqlalchemy import select

async def check_logs():
    async with AsyncSessionLocal() as db:
        stmt = select(QALog).order_by(QALog.created_at.desc()).limit(5)
        result = await db.execute(stmt)
        logs = result.scalars().all()
        metrics_rows = []
        for log in logs:
            metrics = qa_metrics.extract_chat_metrics(getattr(log, "token_usage", None))
            metrics_rows.append(metrics)
            print(
                " | ".join(
                    [
                        f"ID: {log.id}",
                        f"Workflow: {metrics.get('workflow') or 'unknown'}",
                        f"Route: {metrics.get('route') or 'unknown'}",
                        f"Status: {metrics.get('status') or log.status}",
                        f"Products: {metrics.get('product_count', 0)}",
                        f"FollowUps: {metrics.get('follow_up_count', 0)}",
                        f"Created: {log.created_at}",
                    ]
                )
            )
        print(f"Summary: {qa_metrics.summarize_chat_metrics(metrics_rows)}")

if __name__ == "__main__":
    asyncio.run(check_logs())
