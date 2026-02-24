import asyncio
import os
import sys

# Assume running from 'backend' directory
sys.path.append(os.getcwd())

from app.db.session import AsyncSessionLocal
from app.services.legacy.rag_service_deprecated import rag_service
import logging

# Suppress INFO logs
logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

async def debug_retrieval(query: str):
    with open("debug_output.txt", "w") as f:
        f.write(f"Query: '{query}'\n")
        async with AsyncSessionLocal() as db:
            # Search with a very low threshold to see what comes back
            f.write("\n--- Searching with 0.0 threshold ---\n")
            chunks = await rag_service.search_similar_chunks(db, query, limit=5, similarity_threshold=0.0)
            
            if not chunks:
                f.write("No chunks found at all.\n")
            else:
                for i, c in enumerate(chunks):
                    f.write(f"[{i}] Score: {c['similarity']:.4f} | Content: {c['content'][:100]}...\n")
            
            # Check normal threshold
            f.write("\n--- Searching with default (0.5) threshold ---\n")
            chunks_strict = await rag_service.search_similar_chunks(db, query, limit=5, similarity_threshold=0.5)
            if not chunks_strict:
                f.write("No chunks passed the 0.5 threshold.\n")
            else:
                f.write(f"Found {len(chunks_strict)} chunks.\n")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        q = sys.argv[1]
    else:
        q = "test"
    
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(debug_retrieval(q))
