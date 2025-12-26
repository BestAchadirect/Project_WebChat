import asyncio
import os
import sys
from sqlalchemy import text

# Add parent directory to path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import engine

async def check():
    output = []
    async with engine.begin() as conn:
        output.append("--- Sample Master Codes ---")
        res = await conn.execute(text("SELECT DISTINCT master_code FROM products WHERE master_code IS NOT NULL LIMIT 10;"))
        for r in res.fetchall():
            output.append(str(r[0]))

    with open("db_check_results.txt", "w") as f:
        f.write("\n".join(output))
    print("Results written to db_check_results.txt")

if __name__ == "__main__":
    asyncio.run(check())
