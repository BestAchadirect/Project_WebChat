from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import chat_service
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Main chat endpoint.
    
    Handles:
    1. Intent classification (product, FAQ, both)
    2. RAG for FAQ questions
    3. Magento product search
    4. LLM response generation
    """
    try:
        response = await chat_service.process_chat(db=db, request=request)
        return response
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing chat: {str(e)}"
        )
