from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class ChatMessageMetadata(BaseModel):
    products: Optional[List[Any]] = None
    responseTime: Optional[float] = None


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    timestamp: datetime
    metadata: Optional[ChatMessageMetadata] = None


class ChatLogResponse(BaseModel):
    id: str
    sessionId: str
    userId: Optional[str] = None
    startedAt: datetime
    endedAt: Optional[datetime] = None
    messageCount: int
    userSatisfaction: Optional[float] = None
    messages: List[ChatMessageResponse] = []


class ChatStatsResponse(BaseModel):
    totalChats: int
    totalMessages: int
    avgResponseTime: float
    userSatisfaction: float
    period: str
