from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.models.document import DocumentStatus

# Document Schemas
class DocumentBase(BaseModel):
    filename: str

class DocumentCreate(DocumentBase):
    pass

class DocumentResponse(DocumentBase):
    id: UUID
    file_path: Optional[str] = None
    content_hash: Optional[str] = None
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
