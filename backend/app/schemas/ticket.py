from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional

class TicketBase(BaseModel):
    description: str
    image_url: Optional[str] = None
    image_urls: Optional[list[str]] = None

class TicketCreate(TicketBase):
    user_id: str

class TicketUpdate(BaseModel):
    status: Optional[str] = None
    ai_summary: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: Optional[list[str]] = None

class TicketRead(TicketBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: str
    status: str
    ai_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime
