import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.models.knowledge import KnowledgeChunk, KnowledgeEmbedding

async def count():
    async with AsyncSessionLocal() as db:
        c_count = await db.scalar(select(func.count()).select_from(KnowledgeChunk))
        e_count = await db.scalar(select(func.count()).select_from(KnowledgeEmbedding))
        with open("count_output.txt", "w") as f:
            f.write(f"Chunks: {c_count}\n")
            f.write(f"Embeddings: {e_count}\n")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(count())
