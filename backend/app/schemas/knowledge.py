from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel

from app.models.knowledge import KnowledgeUploadStatus

class KnowledgeUploadResponse(BaseModel):
    id: UUID
    filename: str
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    uploaded_by: Optional[str] = None
    status: KnowledgeUploadStatus
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    articles_count: int = 0

    class Config:
        from_attributes = True


class KnowledgeUploadListResponse(BaseModel):
    items: list[KnowledgeUploadResponse]
    totalItems: int
    page: int
    pageSize: int
    totalPages: int

class KnowledgeImportResponse(BaseModel):
    message: str
    upload_id: UUID
    stats: dict
    status: KnowledgeUploadStatus
