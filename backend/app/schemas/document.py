from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from uuid import UUID
from app.models.document import DocumentStatus

class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    status: DocumentStatus
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class DocumentUploadResponse(BaseModel):
    document_id: UUID
    filename: str
    status: DocumentStatus
    message: str

class DocumentListResponse(BaseModel):
    items: List[DocumentResponse]
    total: int
