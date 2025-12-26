import asyncio
import os
import sys
from sqlalchemy import text

# Add parent directory to path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import engine

async def check():
    async with engine.begin() as conn:
        print("--- stockstatus Enum Labels ---")
        res = await conn.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE pg_type.typname = 'stockstatus';"))
        labels = [r[0] for r in res.fetchall()]
        print(f"Labels: {labels}")

if __name__ == "__main__":
    asyncio.run(check())
