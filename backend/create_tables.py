import asyncio
from app.db.session import engine
from app.db.base import Base
# Import all models to ensure they are registered with Base metadata
from app.models import (
    Document, Embedding, 
    Product, ProductEmbedding,
    KnowledgeArticle, KnowledgeEmbedding,
    AppUser, Conversation, Message
)

async def create_tables():
    print("Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully.")

if __name__ == "__main__":
    asyncio.run(create_tables())
