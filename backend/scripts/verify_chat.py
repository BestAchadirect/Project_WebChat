import asyncio
import os
import sys
import json
import logging

# Assume running from 'backend' directory
sys.path.append(os.getcwd())

from app.services.chat.service import ChatService
from app.schemas.chat import ChatRequest
from app.db.session import AsyncSessionLocal
from app.core.config import settings

# Suppress ALL logs
logging.getLogger().handlers = []
logging.basicConfig(level=logging.CRITICAL)
for key in logging.Logger.manager.loggerDict:
    logging.getLogger(key).setLevel(logging.CRITICAL)

async def verify_chat(query: str):
    print(f"Query: '{query}'", flush=True)
    
    async with AsyncSessionLocal() as db:
        service = ChatService(db)
        
        req = ChatRequest(
            user_id="test-user",
            conversation_id=123,
            message=query,
            locale="en-US"
        )
        
        try:
            response = await service.process_chat(req)
            print(f"\nResponse Text: {response.reply_text}", flush=True)
            print(f"Carousel Msg: {response.carousel_msg}", flush=True)
            print(f"Intent (Route): {response.intent}", flush=True)
            
            # Check debug info if available
            if response.debug:
                print(f"\nDebug Info: {json.dumps(response.debug, indent=2)}", flush=True)
                
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        q = sys.argv[1]
    else:
        q = "Can you do coding?"
    
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(verify_chat(q))
