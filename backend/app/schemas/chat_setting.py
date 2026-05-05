from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

class ChatSettingBase(BaseModel):
    title: str = "Jewelry Assistant"
    primary_color: str = "#214166"
    welcome_message: str = "Welcome to our wholesale body jewelry support! 👋 How can I help you today?"
    faq_suggestions: List[str] = [
        "What is your minimum order?",
        "Do you offer custom designs?",
        "What materials do you use?"
    ]

class ChatSettingUpdate(ChatSettingBase):
    pass

class ChatSettingRead(ChatSettingBase):
    id: int
    merchant_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
