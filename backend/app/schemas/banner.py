from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class BannerBase(BaseModel):
    image_url: str
    link_url: Optional[str] = None
    alt_text: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0


class BannerCreateUpdate(BannerBase):
    id: Optional[int] = None


class BannerRead(BannerBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BannerUploadResponse(BaseModel):
    image_url: str
