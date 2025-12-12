import asyncio
from app.db.session import engine
from app.db.base import Base
from sqlalchemy import text

async def drop_tables():
    async with engine.begin() as conn:
        # Drop tables with cascade to handle dependencies
        await conn.execute(text("DROP TABLE IF EXISTS message CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS conversation CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS app_user CASCADE"))
        # Drop old tables if they exist
        await conn.execute(text("DROP TABLE IF EXISTS messages CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS chat_sessions CASCADE"))
        
        await conn.execute(text("DROP TABLE IF EXISTS knowledge_embeddings CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS knowledge_articles CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS product_embeddings CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS products CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS embeddings CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS documents CASCADE"))
        print("Tables dropped.")

if __name__ == "__main__":
    asyncio.run(drop_tables())
