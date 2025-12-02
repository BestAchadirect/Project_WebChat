import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def test_connection():
    # Read DATABASE_URL from .env
    import os
    from dotenv import load_dotenv
    
    load_dotenv('../.env')
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        print("❌ DATABASE_URL not found in .env file")
        return False
    
    print(f"📝 DATABASE_URL format: {database_url[:20]}...{database_url[-20:]}")
    
    # Convert to asyncpg
    if database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+asyncpg://')
    
    print(f"🔄 Testing connection...")
    
    try:
        engine = create_async_engine(database_url, echo=False)
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ Connection successful!")
            print(f"📊 PostgreSQL version: {version}")
            
            # Test pgvector
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                print(f"✅ pgvector extension enabled")
            except Exception as e:
                print(f"⚠️  pgvector extension: {e}")
            
        await engine.dispose()
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {type(e).__name__}")
        print(f"   Error: {str(e)}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)
