from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.dependencies import get_db
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatHistoryResponse,
    ChatHistoryMessage,
    ActiveConversationResponse,
)
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


@router.get("/active", response_model=ActiveConversationResponse)
async def get_active_conversation(
    user_id: str = Query(...),
    conversation_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ActiveConversationResponse:
    service = ChatService(db)
    user = await service.get_user(user_id)
    if not user:
        return ActiveConversationResponse(conversation_id=None)

    conversation = await service.get_active_conversation(user, conversation_id=conversation_id)
    return ActiveConversationResponse(conversation_id=conversation.id if conversation else None)


@router.get("/history/{conversation_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    conversation_id: int,
    user_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> ChatHistoryResponse:
    service = ChatService(db)
    user = await service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation = await service.get_conversation_for_user(user, conversation_id)
    if not conversation or not service.is_conversation_active(conversation):
        raise HTTPException(status_code=404, detail="Conversation not found")

    history = await service.get_history(conversation_id, limit=limit)
    messages = [
        ChatHistoryMessage(
            role=str(item.get("role") or ""),
            content=str(item.get("content") or ""),
            product_data=item.get("product_data"),
            created_at=item.get("created_at"),
        )
        for item in history
    ]
    return ChatHistoryResponse(conversation_id=conversation_id, messages=messages)
