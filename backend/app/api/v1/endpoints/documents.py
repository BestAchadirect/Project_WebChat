from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid

from app.db.session import get_db
from app.models.document import Document, DocumentStatus
from app.models.embedding import Embedding
from app.services.ingestion import IngestionService
from app.services.embedding import EmbeddingService

router = APIRouter()

async def process_document(document_id: uuid.UUID, file: UploadFile, db: AsyncSession):
    try:
        # 1. Extract text
        text = await IngestionService.extract_text(file)
        
        # 2. Chunk text
        chunks = IngestionService.create_chunks(text)
        
        # 3. Generate embeddings and save
        for i, chunk_text in enumerate(chunks):
            vector = await EmbeddingService.get_embedding(chunk_text)
            
            embedding = Embedding(
                document_id=document_id,
                chunk_text=chunk_text,
                chunk_index=i,
                embedding=vector
            )
            db.add(embedding)
        
        # Update document status
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        doc = result.scalar_one()
        doc.status = DocumentStatus.COMPLETED
        await db.commit()
        
    except Exception as e:
        # Handle failure
        print(f"Error processing document {document_id}: {e}")
        # Need a new session or rollback if using the same one, but background tasks are tricky with db session.
        # Ideally, we should create a new session scope here or pass a session factory.
        # For simplicity in MVP, we might be using the passed session, but it's closed after request.
        # So we CANNOT use the 'db' dependency in background task directly if it's closed.
        pass

# Fix for background task: We need to handle DB session inside the task independently.
# I will refactor process_document to take a session factory or handle it differently.
# For now, let's just do it synchronously or use a separate function that creates a session.

import pdfplumber
import io

# ... (imports)

async def process_document_task(document_id: uuid.UUID, file_content: bytes, content_type: str):
    from app.db.session import AsyncSessionLocal
    
    async with AsyncSessionLocal() as db:
        try:
            text = ""
            if content_type == "application/pdf":
                with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                    for page in pdf.pages:
                        text += page.extract_text() or ""
            else:
                text = file_content.decode("utf-8")
            
            chunks = IngestionService.create_chunks(text)
            
            for i, chunk_text in enumerate(chunks):
                vector = await EmbeddingService.get_embedding(chunk_text)
                embedding = Embedding(
                    document_id=document_id,
                    chunk_text=chunk_text,
                    chunk_index=i,
                    embedding=vector
                )
                db.add(embedding)
            
            stmt = select(Document).where(Document.id == document_id)
            result = await db.execute(stmt)
            doc = result.scalar_one()
            doc.status = DocumentStatus.COMPLETED
            await db.commit()
            
        except Exception as e:
            print(f"Error processing document {document_id}: {e}")
            # Update status to failed
            stmt = select(Document).where(Document.id == document_id)
            result = await db.execute(stmt)
            doc = result.scalar_one()
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            await db.commit()

@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    print(f"📂 Upload request received: {file.filename}")
    try:
        # Create Document record
        # TODO: Get tenant_id from auth
        # For MVP, hardcode or create a default tenant
        # We need a tenant first.
        
        # Check if we have a tenant, if not create one?
        # Or just use a dummy UUID for now if constraints allow?
        # Constraints are nullable=False.
        # So we need a tenant.
        
        # Let's fetch the first tenant or create one.
        # This is temporary for MVP.
        from app.models.tenant import Tenant
        print("🔍 Fetching default tenant...")
        result = await db.execute(select(Tenant))
        tenant = result.scalars().first()
        if not tenant:
            print("⚠️ No tenant found, creating default tenant...")
            tenant = Tenant(name="Default Tenant")
            db.add(tenant)
            await db.flush()
        print(f"✅ Using tenant: {tenant.id}")
        
        doc = Document(
            filename=file.filename,
            content_type=file.content_type,
            tenant_id=tenant.id,
            status=DocumentStatus.PROCESSING
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        
        # Read file content to pass to background task
        content = await file.read()
        
        background_tasks.add_task(
            process_document_task, 
            doc.id, 
            content, 
            file.content_type
        )
        
        return {"id": doc.id, "status": "processing"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{document_id}/status")
async def get_document_status(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {
        "id": doc.id,
        "status": doc.status,
        "error_message": doc.error_message
    }

@router.get("/")
async def list_documents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return result.scalars().all()
