from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional

class TicketBase(BaseModel):
    description: str
    image_urls: Optional[list[str]] = None

class TicketCreate(TicketBase):
    user_id: str

class TicketUpdate(BaseModel):
    status: Optional[str] = None
    ai_summary: Optional[str] = None
    admin_reply: Optional[str] = None
    admin_replies: Optional[list[dict[str, str]]] = None
    description: Optional[str] = None
    image_urls: Optional[list[str]] = None

class TicketRead(TicketBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: str
    status: str
    ai_summary: Optional[str] = None
    admin_reply: Optional[str] = None
    admin_replies: Optional[list[dict[str, str]]] = None
    customer_last_activity_at: Optional[datetime] = None
    admin_last_seen_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TicketListResponse(BaseModel):
    items: list[TicketRead]
    totalItems: int
    page: int
    pageSize: int
    totalPages: int
