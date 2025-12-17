from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.product_upload import ProductUploadStatus


class ProductUploadResponse(BaseModel):
    id: UUID
    filename: str
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    uploaded_by: Optional[UUID] = None
    status: ProductUploadStatus
    error_message: Optional[str] = None
    imported_products: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
