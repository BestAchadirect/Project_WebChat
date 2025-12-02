from fastapi import APIRouter
from app.api.v1.endpoints import documents, chat, sessions

api_router = APIRouter()
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
