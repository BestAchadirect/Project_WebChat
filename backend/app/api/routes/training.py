from typing import List, Optional, Any
from uuid import UUID
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.qa_log import QALog
from app.models.knowledge import KnowledgeChunk, KnowledgeArticle, KnowledgeEmbedding
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.training import (
    QALogResponse, ChunkResponse, ChunkUpdate, ChunkListResponse,
    ArticleGroupedResponse, ArticleChunkGroup,
    BulkChunkIds, BulkOperationResponse,
    SimilarityTestRequest, SimilarityTestResponse, SimilarityResult
)
from app.services.embedding import EmbeddingService
from app.services.chat_service import ChatService
from app.core.config import settings

router = APIRouter()
qa_router = APIRouter()

# --- QA Monitoring ---

@qa_router.get("/qa-logs", response_model=List[QALogResponse])
async def list_qa_logs(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(QALog).order_by(desc(QALog.created_at)).offset(offset).limit(limit)
    if status:
        query = query.where(QALog.status == status)
        
    result = await db.execute(query)
    return result.scalars().all()


@qa_router.post("/test-chat", response_model=ChatResponse)
async def qa_test_chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    service = ChatService(db)
    try:
        return await service.process_chat(request, channel="qa_console")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# --- Helper function to build chunk response with metadata ---

async def build_chunk_response(chunk, db: AsyncSession) -> ChunkResponse:
    """Build a ChunkResponse with embedding metadata."""
    # Check if chunk has embedding
    emb_query = select(KnowledgeEmbedding).where(
        KnowledgeEmbedding.chunk_id == chunk.id
    ).order_by(desc(KnowledgeEmbedding.created_at)).limit(1)
    emb_result = await db.execute(emb_query)
    embedding = emb_result.scalars().first()
    
    return ChunkResponse(
        id=chunk.id,
        article_id=chunk.article_id,
        version=chunk.version,
        chunk_index=chunk.chunk_index,
        chunk_text=chunk.chunk_text,
        chunk_hash=chunk.chunk_hash,
        created_at=chunk.created_at,
        article_title=chunk.article.title if chunk.article else None,
        is_embedded=embedding is not None,
        embedded_at=embedding.created_at if embedding else None,
        char_count=len(chunk.chunk_text)
    )


# --- Knowledge Chunks ---

@router.get("/chunks", response_model=ChunkListResponse)
async def list_chunks(
    limit: int = 50,
    offset: int = 0,
    article_id: Optional[UUID] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all knowledge chunks with optional filtering."""
    query = select(KnowledgeChunk).options(
        selectinload(KnowledgeChunk.article)
    ).order_by(KnowledgeChunk.article_id, KnowledgeChunk.chunk_index)
    
    if article_id:
        query = query.where(KnowledgeChunk.article_id == article_id)
    
    if search:
        query = query.where(KnowledgeChunk.chunk_text.ilike(f"%{search}%"))
    
    # Get total count
    count_query = select(func.count()).select_from(KnowledgeChunk)
    if article_id:
        count_query = count_query.where(KnowledgeChunk.article_id == article_id)
    if search:
        count_query = count_query.where(KnowledgeChunk.chunk_text.ilike(f"%{search}%"))
    
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    # Get paginated results
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    chunks = result.scalars().all()
    
    # Build response with metadata
    chunk_responses = []
    for chunk in chunks:
        chunk_resp = await build_chunk_response(chunk, db)
        chunk_responses.append(chunk_resp)
    
    return ChunkListResponse(chunks=chunk_responses, total=total)


# --- Articles with Grouped Chunks ---

@router.get("/articles-grouped", response_model=ArticleGroupedResponse)
async def list_articles_with_chunks(
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all articles with their chunks grouped together."""
    # Get all articles with chunks
    query = select(KnowledgeArticle).options(
        selectinload(KnowledgeArticle.chunks)
    ).order_by(KnowledgeArticle.title)
    
    result = await db.execute(query)
    articles = result.scalars().all()
    
    article_groups = []
    total_chunks = 0
    
    for article in articles:
        chunks = article.chunks
        
        # Filter chunks if search query provided
        if search:
            chunks = [c for c in chunks if search.lower() in c.chunk_text.lower()]
        
        if not chunks:
            continue
            
        # Sort chunks by index
        chunks = sorted(chunks, key=lambda c: c.chunk_index)
        total_chunks += len(chunks)
        
        # Build chunk responses with metadata
        chunk_responses = []
        for chunk in chunks:
            chunk.article = article  # Set article for the helper
            chunk_resp = await build_chunk_response(chunk, db)
            chunk_responses.append(chunk_resp)
        
        article_groups.append(ArticleChunkGroup(
            article_id=article.id,
            article_title=article.title,
            category=article.category,
            chunk_count=len(chunks),
            chunks=chunk_responses
        ))
    
    return ArticleGroupedResponse(
        articles=article_groups,
        total_articles=len(article_groups),
        total_chunks=total_chunks
    )


@router.put("/articles/{article_id}")
async def update_article(
    article_id: UUID,
    title: str,
    db: AsyncSession = Depends(get_db)
):
    """Update an article's title (does not require re-embedding)."""
    query = select(KnowledgeArticle).where(KnowledgeArticle.id == article_id)
    result = await db.execute(query)
    article = result.scalars().first()
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    article.title = title
    await db.commit()
    await db.refresh(article)
    
    return {
        "status": "success",
        "article_id": str(article_id),
        "new_title": article.title
    }


@router.get("/chunks/{chunk_id}", response_model=ChunkResponse)
async def get_chunk(
    chunk_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific chunk by ID."""
    query = select(KnowledgeChunk).options(
        selectinload(KnowledgeChunk.article)
    ).where(KnowledgeChunk.id == chunk_id)
    
    result = await db.execute(query)
    chunk = result.scalars().first()
    
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    return await build_chunk_response(chunk, db)


@router.put("/chunks/{chunk_id}", response_model=ChunkResponse)
async def update_chunk(
    chunk_id: UUID,
    chunk_in: ChunkUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a chunk's text content."""
    query = select(KnowledgeChunk).options(
        selectinload(KnowledgeChunk.article)
    ).where(KnowledgeChunk.id == chunk_id)
    
    result = await db.execute(query)
    chunk = result.scalars().first()
    
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    # Update chunk text, hash and version
    chunk.chunk_text = chunk_in.chunk_text
    chunk.chunk_hash = hashlib.md5(chunk_in.chunk_text.encode()).hexdigest()
    chunk.version += 1
    
    await db.commit()
    await db.refresh(chunk)
    
    return await build_chunk_response(chunk, db)


@router.post("/chunks/{chunk_id}/reembed")
async def reembed_chunk(
    chunk_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Re-generate embedding for a specific chunk."""
    query = select(KnowledgeChunk).options(
        selectinload(KnowledgeChunk.article),
        selectinload(KnowledgeChunk.embeddings)
    ).where(KnowledgeChunk.id == chunk_id)
    
    result = await db.execute(query)
    chunk = result.scalars().first()
    
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    try:
        # Generate new embedding
        embedding_vector = await EmbeddingService.get_embedding(chunk.chunk_text)
        
        # Increment chunk version
        chunk.version += 1
        
        # Delete old embeddings for this chunk
        for old_embedding in chunk.embeddings:
            await db.delete(old_embedding)
        
        # Create new embedding with incremented version
        new_embedding = KnowledgeEmbedding(
            article_id=chunk.article_id,
            chunk_id=chunk.id,
            chunk_text=chunk.chunk_text,
            embedding=embedding_vector,
            model=settings.EMBEDDING_MODEL,
            version=chunk.version
        )
        db.add(new_embedding)
        
        await db.commit()
        
        return {
            "status": "success",
            "message": "Chunk re-embedded successfully",
            "chunk_id": str(chunk_id)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to re-embed chunk: {str(e)}")


# --- Bulk Operations ---

@router.post("/chunks/bulk/reembed", response_model=BulkOperationResponse)
async def bulk_reembed_chunks(
    data: BulkChunkIds,
    db: AsyncSession = Depends(get_db)
):
    """Re-embed multiple chunks at once."""
    processed = 0
    failed = 0
    
    for chunk_id in data.chunk_ids:
        try:
            query = select(KnowledgeChunk).options(
                selectinload(KnowledgeChunk.embeddings)
            ).where(KnowledgeChunk.id == chunk_id)
            
            result = await db.execute(query)
            chunk = result.scalars().first()
            
            if not chunk:
                failed += 1
                continue
            
            # Generate new embedding
            embedding_vector = await EmbeddingService.get_embedding(chunk.chunk_text)
            
            # Increment chunk version
            chunk.version += 1
            
            # Delete old embeddings
            for old_embedding in chunk.embeddings:
                await db.delete(old_embedding)
            
            # Create new embedding with incremented version
            new_embedding = KnowledgeEmbedding(
                article_id=chunk.article_id,
                chunk_id=chunk.id,
                chunk_text=chunk.chunk_text,
                embedding=embedding_vector,
                model=settings.EMBEDDING_MODEL,
                version=chunk.version
            )
            db.add(new_embedding)
            processed += 1
            
        except Exception:
            failed += 1
    
    await db.commit()
    
    return BulkOperationResponse(
        status="completed",
        processed=processed,
        failed=failed,
        message=f"Re-embedded {processed} chunks, {failed} failed"
    )


@router.post("/chunks/bulk/delete", response_model=BulkOperationResponse)
async def bulk_delete_chunks(
    data: BulkChunkIds,
    db: AsyncSession = Depends(get_db)
):
    """Delete multiple chunks at once."""
    processed = 0
    failed = 0
    
    for chunk_id in data.chunk_ids:
        try:
            query = select(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id)
            result = await db.execute(query)
            chunk = result.scalars().first()
            
            if not chunk:
                failed += 1
                continue
            
            await db.delete(chunk)
            processed += 1
            
        except Exception:
            failed += 1
    
    await db.commit()
    
    return BulkOperationResponse(
        status="completed",
        processed=processed,
        failed=failed,
        message=f"Deleted {processed} chunks, {failed} failed"
    )


# --- Similarity Test ---

@router.post("/similarity-test", response_model=SimilarityTestResponse)
async def test_similarity(
    request: SimilarityTestRequest,
    db: AsyncSession = Depends(get_db)
):
    """Test a query against the knowledge base and return similar chunks with scores."""
    try:
        # Generate embedding for query
        query_embedding = await EmbeddingService.get_embedding(request.query)
        
        # Use pgvector to find similar chunks
        from sqlalchemy import text
        
        # Query for similar embeddings using cosine distance
        sql = text("""
            SELECT 
                ke.chunk_id,
                ke.chunk_text,
                ka.title as article_title,
                1 - (ke.embedding <=> :query_embedding::vector) as similarity
            FROM knowledge_embeddings ke
            LEFT JOIN knowledge_articles ka ON ke.article_id = ka.id
            WHERE ke.chunk_id IS NOT NULL
            ORDER BY ke.embedding <=> :query_embedding::vector
            LIMIT :limit
        """)
        
        result = await db.execute(sql, {
            "query_embedding": str(query_embedding),
            "limit": request.limit
        })
        rows = result.fetchall()
        
        results = []
        for row in rows:
            results.append(SimilarityResult(
                chunk_id=row.chunk_id,
                chunk_text=row.chunk_text,
                article_title=row.article_title,
                similarity_score=float(row.similarity) if row.similarity else 0.0
            ))
        
        return SimilarityTestResponse(
            query=request.query,
            results=results
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Similarity test failed: {str(e)}")
