from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.document import Document, DocumentStatus
from app.models.embedding import Embedding
from app.utils.file_parsers import parse_uploaded_file
from app.utils.text_splitter import TextSplitter
from app.utils.supabase_storage import supabase_storage
from app.services.llm_service import llm_service
from app.core.logging import get_logger
from app.core.exceptions import DocumentNotFoundException, DocumentProcessingException
import hashlib
from app.db.session import AsyncSessionLocal

logger = get_logger(__name__)

class DocumentService:
    """Service for document upload and processing."""
    
    def __init__(self):
        self.text_splitter = TextSplitter(chunk_size=1000, chunk_overlap=200)
    
    async def create_document(
        self,
        db: AsyncSession,
        filename: str,
        file_content: bytes,
        content_type: str = None
    ) -> Document:
        """
        Create a new document record and upload file to Supabase Storage.
        
        Args:
            db: Database session
            filename: Original filename
            file_content: File content as bytes
            content_type: MIME type of the file
        
        Returns:
            Created Document object
        """
        # Calculate content hash
        content_hash = hashlib.sha256(file_content).hexdigest()
        
        # Create document record first to get ID
        document = Document(
            filename=filename,
            content_type=content_type,
            content_hash=content_hash,
            file_size=len(file_content),
            status=DocumentStatus.PENDING
        )
        
        db.add(document)
        await db.commit()
        await db.refresh(document)
        
        # Upload file to Supabase Storage
        try:
            storage_path = await supabase_storage.upload_file_bytes(
                file_content=file_content,
                filename=filename,
                document_id=document.id,
                content_type=content_type or "application/octet-stream"
            )
            
            # Update document with file path
            document.file_path = storage_path
            await db.commit()
            await db.refresh(document)
            
            logger.info(f"Document created and uploaded: {document.id}")
            
        except Exception as e:
            # Mark document as failed if upload fails
            document.status = DocumentStatus.FAILED
            document.error_message = f"Failed to upload to storage: {str(e)}"
            await db.commit()
            logger.error(f"Failed to upload document to storage: {e}")
            raise
        
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
            
            # Download file content from Supabase Storage
            if not document.file_path:
                raise DocumentProcessingException("Document has no file path - file may not have been uploaded")
            
            logger.info(f"Downloading file from Supabase: {document.file_path}")
            file_content = await supabase_storage.download_file(document.file_path)
            
            # Extract text from file
            logger.info(f"Parsing file: {document.filename}")
            text = await parse_uploaded_file(file_content, document.filename)
            
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

    async def process_document_background(self, document_id: UUID) -> None:
        """
        Background wrapper that creates its own DB session so it can be
        scheduled with FastAPI BackgroundTasks without relying on the
        request-scoped session.
        """
        async with AsyncSessionLocal() as db:
            try:
                await self.process_document(db=db, document_id=document_id)
            except Exception as e:
                logger.error(f"Background processing failed for {document_id}: {e}")
    
    async def get_document(
        self,
        db: AsyncSession,
        document_id: UUID
    ) -> Optional[Document]:
        """Get a document by ID."""
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def list_documents(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100
    ) -> List[Document]:
        """List all documents."""
        stmt = (
            select(Document)
            .offset(skip)
            .limit(limit)
            .order_by(Document.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
    
    async def delete_document(
        self,
        db: AsyncSession,
        document_id: UUID
    ) -> bool:
        """
        Delete a document and all its associated embeddings.
        
        Args:
            db: Database session
            document_id: Document ID to delete
        
        Returns:
            True if deleted, False if not found
        """
        # Get document
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        document = result.scalar_one_or_none()
        
        if not document:
            return False
        
        # Delete file from Supabase Storage
        if document.file_path:
            try:
                deleted_from_storage = await supabase_storage.delete_file(document.file_path)
                if deleted_from_storage:
                    logger.info(f"Deleted file from storage: {document.file_path}")
                else:
                    logger.warning(f"Could not delete file from storage: {document.file_path}")
            except Exception as e:
                logger.warning(f"Error deleting file from storage: {e}")
                # Continue with database deletion even if storage deletion fails
        
        # Delete embeddings (cascade should handle this, but being explicit)
        delete_embeddings_stmt = select(Embedding).where(Embedding.document_id == document_id)
        embeddings_result = await db.execute(delete_embeddings_stmt)
        embeddings = embeddings_result.scalars().all()
        
        for embedding in embeddings:
            await db.delete(embedding)
        
        # Delete document
        await db.delete(document)
        await db.commit()
        
        logger.info(f"Deleted document {document_id} with {len(embeddings)} embeddings")
        return True

# Singleton instance
document_service = DocumentService()
