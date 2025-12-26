from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime
from uuid import UUID
from app.models.qa_log import QAStatus

# QA Log
class QALogResponse(BaseModel):
    id: UUID
    question: str
    answer: Optional[str]
    sources: List[Any] = []
    status: QAStatus
    error_message: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# Knowledge Chunk with extended metadata
class ChunkResponse(BaseModel):
    id: UUID
    article_id: UUID
    version: int
    chunk_index: int
    chunk_text: str
    chunk_hash: Optional[str] = None
    created_at: datetime
    article_title: Optional[str] = None
    # Extended metadata
    is_embedded: bool = False
    embedded_at: Optional[datetime] = None
    char_count: int = 0
    
    class Config:
        from_attributes = True


class ChunkUpdate(BaseModel):
    chunk_text: str


class ChunkListResponse(BaseModel):
    chunks: List[ChunkResponse]
    total: int


# Article with grouped chunks
class ArticleChunkGroup(BaseModel):
    article_id: UUID
    article_title: str
    category: Optional[str] = None
    chunk_count: int
    chunks: List[ChunkResponse]
    
    class Config:
        from_attributes = True


class ArticleGroupedResponse(BaseModel):
    articles: List[ArticleChunkGroup]
    total_articles: int
    total_chunks: int


# Bulk operations
class BulkChunkIds(BaseModel):
    chunk_ids: List[UUID]


class BulkOperationResponse(BaseModel):
    status: str
    processed: int
    failed: int
    message: str


# Similarity test
class SimilarityTestRequest(BaseModel):
    query: str
    limit: int = 5


class SimilarityResult(BaseModel):
    chunk_id: UUID
    chunk_text: str
    article_title: Optional[str] = None
    similarity_score: float
    
    class Config:
        from_attributes = True


class SimilarityTestResponse(BaseModel):
    query: str
    results: List[SimilarityResult]
