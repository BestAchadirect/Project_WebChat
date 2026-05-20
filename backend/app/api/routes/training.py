from datetime import datetime
from typing import List, Optional, Any, Dict
from uuid import UUID
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_, cast, String, and_
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.qa_log import QALog, QAStatus
from app.models.knowledge import KnowledgeChunk, KnowledgeArticle, KnowledgeEmbedding
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.training import (
    QALogResponse, QALogListResponse, ChunkResponse, ChunkUpdate, ChunkListResponse,
    ArticleGroupedResponse, ArticleChunkGroup,
    BulkChunkIds, BulkOperationResponse,
    SimilarityTestRequest, SimilarityTestResponse, SimilarityResult
)
from app.services.chat.observability.regression_case_templates import build_review_bundle_from_qa_log
from app.services.chat.observability import qa_metrics
from app.services.embedding import EmbeddingService
from app.services.chat.service import ChatService
from app.core.config import settings
from app.utils.pagination import normalize_pagination

router = APIRouter()
qa_router = APIRouter()

REVIEW_STATUS_VALUES = {"passed", "needs_review", "failed"}
AGENTIC_ISSUE_VALUES = {
    "expected_tool_missing",
    "grounding_failed",
    "fallback_to_component",
    "tool_first_selected",
}


def _chat_metric_text(key: str):
    return func.lower(
        func.coalesce(QALog.token_usage["chat_metrics"][key].astext, "")
    )


def _chat_metric_bool(key: str):
    return _chat_metric_text(key) == "true"


def _chat_metric_eq(key: str, value: str):
    return _chat_metric_text(key) == str(value or "").strip().lower()


def _normalize_agentic_issue(agentic_issue: str) -> str:
    normalized = agentic_issue.strip().lower().replace("-", "_")
    if normalized not in AGENTIC_ISSUE_VALUES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid agenticIssue. Expected one of: "
                "expected_tool_missing, grounding_failed, fallback_to_component, tool_first_selected."
            ),
        )
    return normalized


def build_agentic_issue_clause(agentic_issue: str):
    normalized = _normalize_agentic_issue(agentic_issue)
    if normalized == "expected_tool_missing":
        return or_(
            _chat_metric_bool("agentic_expected_tool_missing"),
            _chat_metric_eq("agentic_fallback_reason", "agentic_expected_tool_missing"),
            _chat_metric_eq("harness_fallback_reason", "agentic_expected_tool_missing"),
        )
    if normalized == "grounding_failed":
        return or_(
            _chat_metric_bool("agentic_grounding_failed"),
            _chat_metric_eq("agentic_fallback_reason", "agentic_grounding_failed"),
            _chat_metric_eq("harness_fallback_reason", "agentic_grounding_failed"),
        )
    if normalized == "fallback_to_component":
        return _chat_metric_bool("agentic_fallback_to_component")
    return _chat_metric_bool("tool_first_selected")


def build_harness_tool_clause(harness_tool: str):
    tool_value = str(harness_tool or "").strip()
    if not tool_value:
        raise HTTPException(status_code=400, detail="harnessTool must not be empty.")
    return QALog.token_usage["chat_metrics"]["harness_tools_called"].contains([tool_value])


def build_review_status_clause(review_status: str):
    normalized = review_status.strip().lower()
    if normalized not in REVIEW_STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail="Invalid reviewStatus. Expected one of: passed, needs_review, failed.",
        )

    failure_expr = _chat_metric_text("failure_bucket")
    grounding_expr = _chat_metric_text("grounding_status")
    has_review_failure = and_(failure_expr != "", failure_expr != "other")
    has_grounding_issue = and_(grounding_expr != "", grounding_expr != "grounded")
    has_agentic_review_issue = or_(
        _chat_metric_bool("agentic_expected_tool_missing"),
        _chat_metric_bool("agentic_grounding_failed"),
        _chat_metric_bool("agentic_fallback_to_component"),
    )

    if normalized == "failed":
        return QALog.status == QAStatus.FAILED
    if normalized == "passed":
        return and_(
            QALog.status == QAStatus.SUCCESS,
            ~has_review_failure,
            ~has_grounding_issue,
            ~has_agentic_review_issue,
        )
    return and_(
        QALog.status != QAStatus.FAILED,
        or_(
            QALog.status.in_([QAStatus.NO_ANSWER, QAStatus.FALLBACK]),
            has_agentic_review_issue,
            and_(
                QALog.status == QAStatus.SUCCESS,
                or_(has_review_failure, has_grounding_issue),
            ),
        ),
    )

# --- QA Monitoring ---

@qa_router.get("/qa-logs", response_model=QALogListResponse)
async def list_qa_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=9999),
    status: Optional[str] = None,
    review_status: Optional[str] = Query(None, alias="reviewStatus"),
    channel: Optional[str] = None,
    workflow: Optional[str] = Query(None),
    grounding_status: Optional[str] = Query(None, alias="groundingStatus"),
    failure_bucket: Optional[str] = Query(None, alias="failureBucket"),
    agentic_issue: Optional[str] = Query(None, alias="agenticIssue"),
    agentic_fallback_reason: Optional[str] = Query(None, alias="agenticFallbackReason"),
    harness_tool: Optional[str] = Query(None, alias="harnessTool"),
    created_from: Optional[datetime] = Query(None, alias="createdFrom"),
    created_to: Optional[datetime] = Query(None, alias="createdTo"),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    if "limit" in request.query_params or "offset" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="limit/offset pagination is no longer supported. Use page and pageSize.",
        )

    query = select(QALog)
    count_query = select(func.count()).select_from(QALog)
    if created_from and created_to and created_to < created_from:
        raise HTTPException(
            status_code=400,
            detail="createdTo must be greater than or equal to createdFrom.",
        )
    if status:
        query = query.where(QALog.status == status)
        count_query = count_query.where(QALog.status == status)
    if review_status:
        review_clause = build_review_status_clause(review_status)
        query = query.where(review_clause)
        count_query = count_query.where(review_clause)
    if channel:
        channel_value = channel.strip()
        if channel_value:
            if channel_value.lower() == "unlabeled":
                query = query.where(or_(QALog.channel.is_(None), QALog.channel == ""))
                count_query = count_query.where(or_(QALog.channel.is_(None), QALog.channel == ""))
            else:
                query = query.where(QALog.channel == channel_value)
                count_query = count_query.where(QALog.channel == channel_value)
    if workflow:
        workflow_value = workflow.strip().lower()
        if workflow_value:
            workflow_expr = _chat_metric_text("workflow")
            query = query.where(workflow_expr == workflow_value)
            count_query = count_query.where(workflow_expr == workflow_value)
    if grounding_status:
        grounding_value = grounding_status.strip().lower()
        if grounding_value:
            grounding_expr = _chat_metric_text("grounding_status")
            query = query.where(grounding_expr == grounding_value)
            count_query = count_query.where(grounding_expr == grounding_value)
    if failure_bucket:
        failure_value = failure_bucket.strip().lower()
        if failure_value:
            failure_expr = _chat_metric_text("failure_bucket")
            query = query.where(failure_expr == failure_value)
            count_query = count_query.where(failure_expr == failure_value)
    if agentic_issue:
        agentic_issue_clause = build_agentic_issue_clause(agentic_issue)
        query = query.where(agentic_issue_clause)
        count_query = count_query.where(agentic_issue_clause)
    if agentic_fallback_reason:
        agentic_fallback_value = agentic_fallback_reason.strip().lower()
        if agentic_fallback_value:
            fallback_expr = _chat_metric_text("agentic_fallback_reason")
            query = query.where(fallback_expr == agentic_fallback_value)
            count_query = count_query.where(fallback_expr == agentic_fallback_value)
    if harness_tool:
        harness_tool_clause = build_harness_tool_clause(harness_tool)
        query = query.where(harness_tool_clause)
        count_query = count_query.where(harness_tool_clause)
    if created_from:
        query = query.where(QALog.created_at >= created_from)
        count_query = count_query.where(QALog.created_at >= created_from)
    if created_to:
        query = query.where(QALog.created_at <= created_to)
        count_query = count_query.where(QALog.created_at <= created_to)
    if search:
        search_value = search.strip()
        if search_value:
            search_like = f"%{search_value}%"
            query = query.where(or_(QALog.question.ilike(search_like), QALog.answer.ilike(search_like)))
            count_query = count_query.where(or_(QALog.question.ilike(search_like), QALog.answer.ilike(search_like)))

    total = int((await db.execute(count_query)).scalar() or 0)
    safe_page, total_pages, offset = normalize_pagination(
        total_items=total,
        page=page,
        page_size=page_size,
    )
    query = query.order_by(desc(QALog.created_at)).offset(offset).limit(page_size)

    result = await db.execute(query)
    return QALogListResponse(
        items=result.scalars().all(),
        totalItems=total,
        page=safe_page,
        pageSize=page_size,
        totalPages=total_pages,
    )


@qa_router.get("/qa-logs/rollout-summary", response_model=Dict[str, Any])
async def get_qa_rollout_summary(
    review_status: Optional[str] = Query(None, alias="reviewStatus"),
    channel: Optional[str] = None,
    workflow: Optional[str] = Query(None),
    grounding_status: Optional[str] = Query(None, alias="groundingStatus"),
    failure_bucket: Optional[str] = Query(None, alias="failureBucket"),
    agentic_issue: Optional[str] = Query(None, alias="agenticIssue"),
    agentic_fallback_reason: Optional[str] = Query(None, alias="agenticFallbackReason"),
    harness_tool: Optional[str] = Query(None, alias="harnessTool"),
    created_from: Optional[datetime] = Query(None, alias="createdFrom"),
    created_to: Optional[datetime] = Query(None, alias="createdTo"),
    max_rows: int = Query(5000, alias="maxRows", ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if created_from and created_to and created_to < created_from:
        raise HTTPException(
            status_code=400,
            detail="createdTo must be greater than or equal to createdFrom.",
        )

    query = select(QALog.token_usage)
    if review_status:
        query = query.where(build_review_status_clause(review_status))
    if channel:
        channel_value = channel.strip()
        if channel_value:
            if channel_value.lower() == "unlabeled":
                query = query.where(or_(QALog.channel.is_(None), QALog.channel == ""))
            else:
                query = query.where(QALog.channel == channel_value)
    if workflow:
        workflow_value = workflow.strip().lower()
        if workflow_value:
            query = query.where(_chat_metric_text("workflow") == workflow_value)
    if grounding_status:
        grounding_value = grounding_status.strip().lower()
        if grounding_value:
            query = query.where(_chat_metric_text("grounding_status") == grounding_value)
    if failure_bucket:
        failure_value = failure_bucket.strip().lower()
        if failure_value:
            query = query.where(_chat_metric_text("failure_bucket") == failure_value)
    if agentic_issue:
        query = query.where(build_agentic_issue_clause(agentic_issue))
    if agentic_fallback_reason:
        agentic_fallback_value = agentic_fallback_reason.strip().lower()
        if agentic_fallback_value:
            query = query.where(_chat_metric_text("agentic_fallback_reason") == agentic_fallback_value)
    if harness_tool:
        query = query.where(build_harness_tool_clause(harness_tool))
    if created_from:
        query = query.where(QALog.created_at >= created_from)
    if created_to:
        query = query.where(QALog.created_at <= created_to)

    query = query.order_by(desc(QALog.created_at)).limit(max_rows)
    result = await db.execute(query)
    metric_rows = [
        qa_metrics.extract_chat_metrics(token_usage)
        for token_usage in list(result.scalars().all())
    ]
    return {
        "sampledRows": len(metric_rows),
        "maxRows": max_rows,
        "filters": {
            "reviewStatus": review_status,
            "channel": channel,
            "workflow": workflow,
            "groundingStatus": grounding_status,
            "failureBucket": failure_bucket,
            "agenticIssue": agentic_issue,
            "agenticFallbackReason": agentic_fallback_reason,
            "harnessTool": harness_tool,
            "createdFrom": created_from.isoformat() if created_from else None,
            "createdTo": created_to.isoformat() if created_to else None,
        },
        "toolFirst": qa_metrics.build_tool_first_rollout_summary(metric_rows),
    }


@qa_router.get("/qa-logs/{qa_log_id}/review-bundle", response_model=Dict[str, Any])
async def get_qa_log_review_bundle(
    qa_log_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    result = await db.execute(select(QALog).where(QALog.id == qa_log_id))
    qa_log = result.scalar_one_or_none()
    if qa_log is None:
        raise HTTPException(status_code=404, detail="QA log not found")
    return build_review_bundle_from_qa_log(qa_log)


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
    search_uuid: Optional[UUID] = None
    if search:
        try:
            search_uuid = UUID(search.strip())
        except ValueError:
            search_uuid = None

    query = select(KnowledgeChunk).options(
        selectinload(KnowledgeChunk.article)
    ).order_by(KnowledgeChunk.article_id, KnowledgeChunk.chunk_index)
    
    if article_id:
        query = query.where(KnowledgeChunk.article_id == article_id)
    
    if search_uuid:
        query = query.where(KnowledgeChunk.id == search_uuid)
    elif search:
        search_like = f"%{search}%"
        query = query.where(KnowledgeChunk.chunk_text.ilike(search_like))
    
    # Get total count
    count_query = select(func.count()).select_from(KnowledgeChunk)
    if article_id:
        count_query = count_query.where(KnowledgeChunk.article_id == article_id)
    if search_uuid:
        count_query = count_query.where(KnowledgeChunk.id == search_uuid)
    elif search:
        search_like = f"%{search}%"
        count_query = count_query.where(KnowledgeChunk.chunk_text.ilike(search_like))
    
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
    search_uuid: Optional[UUID] = None
    if search:
        try:
            search_uuid = UUID(search.strip())
        except ValueError:
            search_uuid = None

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
        if search_uuid:
            chunks = [c for c in chunks if c.id == search_uuid]
        elif search:
            search_lower = search.lower()
            chunks = [c for c in chunks if search_lower in c.chunk_text.lower()]
        
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
    chunk.chunk_hash = hashlib.sha256(chunk_in.chunk_text.encode()).hexdigest()
    chunk.version += 1
    if chunk.article:
        current_active = chunk.article.active_version or 0
        if chunk.version > current_active:
            chunk.article.active_version = chunk.version
    
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
        if chunk.article:
            current_active = chunk.article.active_version or 0
            if chunk.version > current_active:
                chunk.article.active_version = chunk.version
        
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
                selectinload(KnowledgeChunk.embeddings),
                selectinload(KnowledgeChunk.article),
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
            if chunk.article:
                current_active = chunk.article.active_version or 0
                if chunk.version > current_active:
                    chunk.article.active_version = chunk.version
            
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
        model = getattr(settings, "KNOWLEDGE_EMBEDDING_MODEL", settings.EMBEDDING_MODEL)
        sql = text("""
            SELECT 
                ke.chunk_id,
                ke.chunk_text,
                ka.title as article_title,
                1 - (ke.embedding <=> :query_embedding::vector) as similarity
            FROM knowledge_embeddings ke
            LEFT JOIN knowledge_articles ka ON ke.article_id = ka.id
            WHERE ke.chunk_id IS NOT NULL
              AND (ke.model IS NULL OR ke.model = :model)
            ORDER BY ke.embedding <=> :query_embedding::vector
            LIMIT :limit
        """)
        
        result = await db.execute(sql, {
            "query_embedding": str(query_embedding),
            "model": model,
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
