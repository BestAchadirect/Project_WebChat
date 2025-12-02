from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List

from app.dependencies import get_db
from app.api.deps import get_current_user, get_current_tenant
from app.schemas.document import DocumentResponse, DocumentUploadResponse
from app.services.document_service import document_service
from app.models.user import User
from app.models.tenant import Tenant

router = APIRouter()

@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant)
):
    """
    Upload a document for processing.
    
    Supported formats: PDF, DOC, DOCX, TXT, CSV
    """
    # Validate file type
    allowed_extensions = [".pdf", ".doc", ".docx", ".txt", ".csv"]
    file_ext = "." + file.filename.split(".")[-1].lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Read file content
    file_content = await file.read()
    
    # Create document record
    document = await document_service.create_document(
        db=db,
        tenant_id=current_tenant.id,
        filename=file.filename,
        file_content=file_content
    )
    
    # TODO: Save file to storage (S3 or local)
    # For now, we'll process in background
    
    # Schedule background processing
    if background_tasks:
        background_tasks.add_task(
            document_service.process_document,
            db=db,
            document_id=document.id
        )
    
    return DocumentUploadResponse(
        document_id=document.id,
        filename=document.filename,
        status=document.status,
        message="Document uploaded successfully. Processing in background."
    )

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant)
):
    """
    Get document by ID.
    """
    document = await document_service.get_document(
        db=db,
        document_id=document_id,
        tenant_id=current_tenant.id
    )
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    return document

@router.get("/", response_model=List[DocumentResponse])
async def list_documents(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant)
):
    """
    List all documents for current tenant.
    """
    documents = await document_service.list_documents(
        db=db,
        tenant_id=current_tenant.id,
        skip=skip,
        limit=limit
    )
    
    return documents
