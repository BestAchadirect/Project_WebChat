import asyncio
import os
import sys

# Add parent to path
sys.path.append(os.getcwd())

from app.services.ai.llm_service import llm_service
from app.db.session import AsyncSessionLocal
from app.core.config import settings

async def check():
    query = "what product do you have in your store"
    print(f"Query: '{query}'")
    
    # Generate embedding
    emb = await llm_service.generate_embedding(query)
    
    async with AsyncSessionLocal() as db:
        # We need to manually call the search logic or use the service if manageable.
        # But ChatService.search_products is what we want.
        # Let's import ChatService instead.
        from app.services.chat.service import ChatService
        service = ChatService(db)
        
        products, distances, best_dist, _ = await service.search_products(
            query_embedding=emb,
            limit=5,
            run_id="test"
        )
        
        print(f"Best Distance: {best_dist}")
        threshold = getattr(settings, "PRODUCT_DISTANCE_THRESHOLD", 0.45)
        print(f"Current Threshold: {threshold}")
        
        if products:
            print("Top Product:", products[0].name)
        else:
            print("No products found.")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check())
