"""
Script to completely drop all tables and recreate only what we need.
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine
from app.db.base import Base
from app.models.document import Document
from app.models.embedding import Embedding
from app.models.chat_session import ChatSession
from app.models.message import Message

async def drop_all_and_recreate():
    async with engine.begin() as conn:
        # Drop ALL tables including any orphaned ones
        print("🗑️  Dropping ALL tables...")
        tables_to_drop = [
            "messages",
            "embeddings", 
            "chat_sessions",
            "documents",
            "users",
            "tenants"
        ]
        
        for table in tables_to_drop:
            try:
                await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                print(f"  ✓ Dropped {table}")
            except Exception as e:
                print(f"  - {table} (not found or already dropped)")
        
        print("✅ All tables dropped")
        
        # Now create only the tables we need
        print("\n📦 Creating new tables...")
        await conn.run_sync(Base.metadata.create_all)
        
        # Enable pgvector extension
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            print("✅ pgvector extension enabled")
        except Exception as e:
            print(f"⚠️  pgvector: {e}")
        
    print("\n✅ Database recreated successfully!")
    print("\n📋 Tables created:")
    print("  - documents")
    print("  - embeddings")
    print("  - chat_sessions")
    print("  - messages")

if __name__ == "__main__":
    asyncio.run(drop_all_and_recreate())

