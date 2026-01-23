import asyncio
from app.db.session import AsyncSessionLocal
from app.models.qa_log import QALog
from sqlalchemy import select

async def check_logs():
    async with AsyncSessionLocal() as db:
        stmt = select(QALog).order_by(QALog.created_at.desc()).limit(5)
        result = await db.execute(stmt)
        logs = result.scalars().all()
        for log in logs:
            print(f"ID: {log.id} | Question: {log.question} | Status: {log.status} | Created: {log.created_at}")

if __name__ == "__main__":
    asyncio.run(check_logs())
