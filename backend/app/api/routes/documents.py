from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.core.config import settings
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    DocumentUpdate
)
from app.services.document_service import document_service

router = APIRouter()


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document and store metadata."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    allowed = [e.strip().lower().lstrip(".") for e in (settings.ALLOWED_EXTENSIONS or "").split(",") if e.strip()]
    if allowed:
        ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "").lower()
        if ext not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Allowed: {', '.join(sorted(set(allowed)))}",
            )

    document = await document_service.upload_document(db, file)
    return DocumentUploadResponse(
        document_id=document.id,
        filename=document.filename,
        status=document.status,
        message="Upload successful",
    )


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List uploaded documents."""
    items, total = await document_service.list_documents(db, skip=skip, limit=limit)
    return DocumentListResponse(items=items, total=total)


    await document_service.delete_document(db, document_id)


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: UUID,
    doc_in: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update document metadata."""
    doc = await document_service.update_document(db, document_id, doc_in)
    return doc

@router.post("/{document_id}/reprocess")
async def reprocess_document(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger reprocessing of the document."""
    # Logic to trigger reprocessing
    # For now, just update status to PROCESSING
    # You might want to call actual processing service here
    doc = await document_service.get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    # TODO: Connect to RAG pipeline
    # background_tasks.add_task(rag_service.process_document, doc.id)
    
    return {"message": "Reprocessing started", "id": doc.id}
