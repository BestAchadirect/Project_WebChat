import asyncio
from app.db.session import engine
from app.db.base import Base
from sqlalchemy import text

async def drop_tables():
    async with engine.begin() as conn:
        # Drop tables with cascade to handle dependencies
        await conn.execute(text("DROP TABLE IF EXISTS embeddings CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS documents CASCADE"))
        print("Tables dropped.")

if __name__ == "__main__":
    asyncio.run(drop_tables())
