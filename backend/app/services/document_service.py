from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.document import Document, DocumentStatus
from app.models.embedding import Embedding
from app.models.tenant import Tenant
from app.utils.file_parsers import parse_uploaded_file
from app.utils.text_splitter import TextSplitter
from app.services.llm_service import llm_service
from app.core.logging import get_logger
from app.core.exceptions import DocumentNotFoundException, DocumentProcessingException
import hashlib

logger = get_logger(__name__)

class DocumentService:
    """Service for document upload and processing."""
    
    def __init__(self):
        self.text_splitter = TextSplitter(chunk_size=1000, chunk_overlap=200)
    
    async def create_document(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        filename: str,
        file_content: bytes
    ) -> Document:
        """
        Create a new document record.
        
        Args:
            db: Database session
            tenant_id: Tenant ID
            filename: Original filename
            file_content: File content as bytes
        
        Returns:
            Created Document object
        """
        # Calculate content hash
        content_hash = hashlib.sha256(file_content).hexdigest()
        
        # Create document record
        document = Document(
            tenant_id=tenant_id,
            filename=filename,
            content_hash=content_hash,
            file_size=len(file_content),
            status=DocumentStatus.PENDING
        )
        
        db.add(document)
        await db.commit()
        await db.refresh(document)
        
        return document
    
    async def process_document(
        self,
        db: AsyncSession,
        document_id: UUID
    ) -> None:
        """
        Process a document: extract text, chunk, and create embeddings.
        This should be called as a background task.
        
        Args:
            db: Database session
            document_id: Document ID to process
        """
        try:
            # Get document
            stmt = select(Document).where(Document.id == document_id)
            result = await db.execute(stmt)
            document = result.scalar_one_or_none()
            
            if not document:
                raise DocumentNotFoundException(str(document_id))
            
            # Update status
            document.status = DocumentStatus.PROCESSING
            await db.commit()
            
            # TODO: Load file content from storage
            # For now, assuming file_path contains the actual content or path
            # In production, you'd load from S3 or local storage
            
            # Placeholder: Extract text
            # text = await parse_uploaded_file(file_content, document.filename)
            text = "Sample document text for processing..."  # Placeholder
            
            # Chunk text
            chunks = self.text_splitter.split_text(text)
            
            # Generate embeddings for all chunks
            embeddings_data = await llm_service.generate_embeddings_batch(chunks)
            
            # Create embedding records
            for idx, (chunk_text, embedding_vector) in enumerate(zip(chunks, embeddings_data)):
                embedding = Embedding(
                    document_id=document.id,
                    chunk_text=chunk_text,
                    chunk_index=idx,
                    embedding=embedding_vector
                )
                db.add(embedding)
            
            # Update document status
            document.status = DocumentStatus.COMPLETED
            await db.commit()
            
            logger.info(f"Successfully processed document {document_id} with {len(chunks)} chunks")
            
        except Exception as e:
            logger.error(f"Error processing document {document_id}: {e}")
            
            # Update document status to failed
            if document:
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)
                await db.commit()
            
            raise DocumentProcessingException(f"Failed to process document: {str(e)}")
    
    async def get_document(
        self,
        db: AsyncSession,
        document_id: UUID,
        tenant_id: UUID
    ) -> Optional[Document]:
        """Get a document by ID."""
        stmt = select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def list_documents(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100
    ) -> List[Document]:
        """List all documents for a tenant."""
        stmt = (
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .offset(skip)
            .limit(limit)
            .order_by(Document.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

# Singleton instance
document_service = DocumentService()
