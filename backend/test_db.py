"""Test database connection"""
import asyncio
from app.db.session import engine
from sqlalchemy import text

async def test_connection():
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("✅ Database connection successful!")
            print(f"Result: {result.scalar()}")
            
            # Test documents table
            result = await conn.execute(text("SELECT COUNT(*) FROM documents"))
            count = result.scalar()
            print(f"✅ Documents table exists, count: {count}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_connection())
