from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.dependencies import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter()

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Unified Chat Endpoint.
    Handles:
    1. Intent Classification
    2. Product/Knowledge Retrieval
    3. AI Response Generation
    """
    service = ChatService(db)
    try:
        response = await service.process_chat(request, channel="widget")
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
