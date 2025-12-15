from typing import List, Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pgvector.sqlalchemy import Vector
from app.models.knowledge import KnowledgeArticle, KnowledgeEmbedding
from app.services.llm_service import llm_service
from app.core.logging import get_logger

logger = get_logger(__name__)

class RAGService:
    """Service for Retrieval-Augmented Generation (RAG) operations."""
    
    async def search_similar_chunks(
        self,
        db: AsyncSession,
        query: str,
        limit: int = 5,
        similarity_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Search for similar document chunks using vector similarity.
        
        Args:
            db: Database session
            query: Search query
            limit: Maximum number of results
            similarity_threshold: Minimum similarity score (0-1)
        
        Returns:
            List of matching chunks with metadata
        """
        try:
            # Generate embedding for query
            query_embedding = await llm_service.generate_embedding(query)
            
            # Perform vector similarity search
            # Using cosine distance (1 - cosine_similarity)
            stmt = (
                select(
                    KnowledgeEmbedding,
                    KnowledgeArticle,
                    KnowledgeEmbedding.embedding.cosine_distance(query_embedding).label("distance")
                )
                .join(KnowledgeArticle, KnowledgeEmbedding.article_id == KnowledgeArticle.id)
                .order_by("distance")
                .limit(limit)
            )
            
            result = await db.execute(stmt)
            rows = result.all()
            
            # Format results
            chunks = []
            for embedding, article, distance in rows:
                similarity = 1 - distance  # Convert distance to similarity
                
                if similarity >= similarity_threshold:
                    chunks.append({
                        "chunk_id": str(embedding.id),
                        "article_id": str(article.id),
                        "article_title": article.title,
                        "content": embedding.chunk_text,
                        "similarity": similarity,
                        "category": article.category
                    })
            
            return chunks
            
        except Exception as e:
            logger.error(f"Error searching similar chunks: {e}")
            raise
    
    async def build_context(
        self,
        db: AsyncSession,
        query: str,
        max_chunks: int = 5
    ) -> str:
        """
        Build context string from relevant document chunks.
        
        Args:
            db: Database session
            query: User query
            max_chunks: Maximum number of chunks to include
        
        Returns:
            Formatted context string
        """
        chunks = await self.search_similar_chunks(
            db=db,
            query=query,
            limit=max_chunks
        )
        
        if not chunks:
            return ""
        
        # Format context
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(
                f"[Source {i}: {chunk['document_name']}]\n{chunk['content']}\n"
            )
        
        return "\n".join(context_parts)

# Singleton instance
rag_service = RAGService()
