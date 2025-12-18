from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.config import settings
from app.models.chat import AppUser, Conversation, Message, MessageRole
from app.models.knowledge import KnowledgeArticle, KnowledgeChunk, KnowledgeChunkTag, KnowledgeEmbedding
from app.models.product import Product, ProductEmbedding
from app.schemas.chat import ChatRequest, ChatResponse, KnowledgeSource, ProductCard
from app.services.llm_service import llm_service

logger = get_logger(__name__)

# Debug-mode NDJSON logging configuration
DEBUG_LOG_PATH = Path(r"c:\Project_WebChat\.cursor\debug.log")


def _debug_log(payload: Dict[str, Any]) -> None:
    """Append a single NDJSON line to the debug log. Never raises."""
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Never let debug logging break the request
        pass


class ChatService:
    """Chat orchestration (intent -> retrieval -> response)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_user(
        self,
        user_id: str,
        name: str | None = None,
        email: str | None = None,
    ) -> AppUser:
        stmt = select(AppUser).where(AppUser.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            # Best-effort update
            if name and not user.customer_name:
                user.customer_name = name
            if email and not user.email:
                user.email = email
            self.db.add(user)
            await self.db.commit()
            return user

        user = AppUser(id=user_id, customer_name=name, email=email)
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def get_or_create_conversation(
        self,
        user: AppUser,
        conversation_id: Optional[int],
    ) -> Conversation:
        if conversation_id:
            stmt = select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                return existing

        conversation = Conversation(user_id=user.id)
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def save_message(self, conversation_id: int, role: str, content: str) -> None:
        msg = Message(conversation_id=conversation_id, role=role, content=content)
        self.db.add(msg)
        await self.db.commit()

    async def get_history(self, conversation_id: int, limit: int = 5) -> List[Dict[str, str]]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        msgs = result.scalars().all()
        return [{"role": m.role, "content": m.content} for m in reversed(msgs)]

    async def search_knowledge(
        self,
        query_text: str,
        query_embedding: List[float],
        limit: int = 10,
        must_tags: Optional[List[str]] = None,
        boost_tags: Optional[List[str]] = None,
        run_id: Optional[str] = None,
    ) -> Tuple[List[KnowledgeSource], Optional[float]]:
        """
        Vector search over knowledge base with optional tag constraints.
        Returns sources and the best (lowest) cosine distance.
        """
        tag_join_needed = bool(must_tags or boost_tags)

        distance_col = KnowledgeEmbedding.embedding.cosine_distance(query_embedding).label("distance")

        stmt = (
            select(
                KnowledgeEmbedding.id,
                KnowledgeEmbedding.chunk_text,
                KnowledgeEmbedding.article_id,
                KnowledgeEmbedding.chunk_id,
                KnowledgeArticle.title,
                KnowledgeArticle.category,
                KnowledgeArticle.url,
                distance_col,
            )
            .join(KnowledgeArticle, KnowledgeEmbedding.article_id == KnowledgeArticle.id)
        )

        if tag_join_needed:
            stmt = stmt.join(KnowledgeChunk, KnowledgeChunk.id == KnowledgeEmbedding.chunk_id)
            stmt = stmt.outerjoin(KnowledgeChunkTag, KnowledgeChunkTag.chunk_id == KnowledgeChunk.id)

        if must_tags or tag_join_needed:
            stmt = stmt.group_by(
                KnowledgeEmbedding.id,
                KnowledgeEmbedding.chunk_text,
                KnowledgeEmbedding.article_id,
                KnowledgeEmbedding.chunk_id,
                KnowledgeArticle.title,
                KnowledgeArticle.category,
                KnowledgeArticle.url,
                distance_col,
            )

        if must_tags:
            required_count = len(set(must_tags))
            stmt = stmt.having(
                func.count(func.distinct(KnowledgeChunkTag.tag)).filter(KnowledgeChunkTag.tag.in_(must_tags))
                == required_count
            )

        if boost_tags:
            boost_case = func.max(case((KnowledgeChunkTag.tag.in_(boost_tags), 1), else_=0)).label("boost_match")
            stmt = stmt.add_columns(boost_case).order_by(distance_col, boost_case.desc())
        else:
            stmt = stmt.order_by(distance_col)

        stmt = stmt.limit(limit)

        result = await self.db.execute(stmt)
        rows: Sequence[Any] = result.all()

        sources: List[KnowledgeSource] = []
        best_distance: Optional[float] = None

        for idx, row in enumerate(rows):
            (
                emb_id,
                chunk_text,
                article_id,
                _chunk_id,
                title,
                category,
                url,
                distance,
                *maybe_boost,
            ) = row
            if best_distance is None:
                best_distance = float(distance)

            similarity = 1 - float(distance)
            sources.append(
                KnowledgeSource(
                    source_id=str(article_id),
                    title=title,
                    content_snippet=chunk_text[:500],
                    category=category,
                    relevance=similarity,
                    url=url,
                )
            )

            # #region agent log
            if run_id and idx < 3:
                try:
                    _debug_log(
                        {
                            "sessionId": "debug-session",
                            "runId": run_id,
                            "hypothesisId": "HK",
                            "location": "chat_service.search_knowledge:top_result",
                            "message": "top knowledge chunk",
                            "data": {
                                "rank": idx + 1,
                                "article_id": str(article_id),
                                "title": title,
                                "distance": float(distance),
                                "threshold": settings.KNOWLEDGE_DISTANCE_THRESHOLD,
                                "snippet": (chunk_text or "")[:200],
                            },
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                except Exception:
                    pass
            # #endregion

        return sources, best_distance

    async def search_products(
        self,
        query_embedding: List[float],
        limit: int = 10,
        run_id: Optional[str] = None,
    ) -> Tuple[List[ProductCard], Optional[float]]:
        """
        Vector search over product embeddings.
        Returns product cards and best (lowest) cosine distance.
        """
        distance_col = ProductEmbedding.embedding.cosine_distance(query_embedding).label("distance")

        probe_stmt = (
            select(ProductEmbedding.product_id, distance_col)
            .join(Product, Product.id == ProductEmbedding.product_id)
            .where(Product.is_active.is_(True))
            .order_by(distance_col)
            .limit(limit)
        )
        probe_result = await self.db.execute(probe_stmt)
        probe_rows: Sequence[Any] = probe_result.all()

        if not probe_rows:
            return [], None

        best_distance = float(probe_rows[0].distance)
        product_id_order = [row.product_id for row in probe_rows]

        # Fetch full product data after probe to keep the probe fast
        products_stmt = select(Product).where(Product.id.in_(product_id_order))
        products_result = await self.db.execute(products_stmt)
        products_by_id = {p.id: p for p in products_result.scalars().all()}

        product_cards: List[ProductCard] = []
        for idx, pid in enumerate(product_id_order):
            product = products_by_id.get(pid)
            if not product:
                continue
            product_cards.append(
                ProductCard(
                    id=product.id,
                    object_id=product.object_id,
                    sku=product.sku,
                    legacy_sku=product.legacy_sku or [],
                    name=product.name,
                    price=product.price,
                    currency=product.currency,
                    image_url=product.image_url,
                    product_url=product.product_url,
                    attributes=product.attributes or {},
                )
            )

            # #region agent log
            if run_id and idx < 3:
                try:
                    _debug_log(
                        {
                            "sessionId": "debug-session",
                            "runId": run_id,
                            "hypothesisId": "HP",
                            "location": "chat_service.search_products:top_result",
                            "message": "top product",
                            "data": {
                                "rank": idx + 1,
                                "product_id": str(product.id),
                                "name": product.name,
                                "distance": best_distance if idx == 0 else None,
                                "threshold": settings.PRODUCT_DISTANCE_THRESHOLD,
                            },
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                except Exception:
                    pass
            # #endregion

        return product_cards, best_distance

    async def keyword_fallback(self, query_text: str, limit: int = 5) -> List[KnowledgeSource]:
        """
        Keyword OR search over knowledge chunks when vector search is weak.
        Scores chunks by how many query keywords they contain.
        """
        # Very small stopword list for English
        stopwords = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "to",
            "for",
            "of",
            "in",
            "on",
            "at",
            "by",
            "with",
            "is",
            "are",
            "was",
            "were",
        }
        tokens = [t.lower() for t in query_text.replace(",", " ").replace(".", " ").split()]
        keywords = [t for t in tokens if len(t) >= 3 and t not in stopwords][:6]

        if not keywords:
            return []

        conditions = [KnowledgeChunk.chunk_text.ilike(f"%{kw}%") for kw in keywords]

        # Build a per-row match count expression without using SQL aggregate functions
        score_expr = None
        for cond in conditions:
            term = case((cond, 1), else_=0)
            score_expr = term if score_expr is None else score_expr + term

        match_count = score_expr.label("match_count") if score_expr is not None else None

        stmt = (
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.chunk_text,
                KnowledgeArticle.id.label("article_id"),
                KnowledgeArticle.title,
                KnowledgeArticle.category,
                KnowledgeArticle.url,
                match_count,
            )
            .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
            .where(or_(*conditions))
        )

        if match_count is not None:
            stmt = stmt.order_by(match_count.desc(), KnowledgeChunk.id)

        stmt = stmt.limit(limit)

        result = await self.db.execute(stmt)
        rows = result.all()

        sources: List[KnowledgeSource] = []
        for chunk_id, chunk_text, article_id, title, category, url, match_value in rows:
            relevance = float(match_value or 0) / max(len(keywords), 1)
            sources.append(
                KnowledgeSource(
                    source_id=str(article_id),
                    title=title,
                    content_snippet=chunk_text[:500],
                    category=category,
                    relevance=relevance,
                    url=url,
                )
            )
        return sources

    async def synthesize_answer(self, question: str, sources: List[KnowledgeSource]) -> str:
        if not sources:
            return (
                "I don't have enough information in my knowledge base to answer that yet. "
                "Try asking another question or rephrasing."
            )

        context = "\n\n".join([f"[{s.title}] {s.content_snippet}" for s in sources[:3]])
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant. Answer using ONLY the provided knowledge context. "
                    "If the answer is not in the context, say you don't have enough information."
                ),
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ]
        try:
            return await llm_service.generate_chat_response(messages, temperature=0.2)
        except Exception as e:
            logger.error(f"LLM response generation failed: {e}")
            return "I'm having trouble generating an answer right now. Please try again."

    async def process_chat(self, req: ChatRequest) -> ChatResponse:
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        _history = await self.get_history(conversation.id)

        run_id = f"chat-{int(time.time() * 1000)}"

        # #region agent log
        _debug_log(
            {
                "sessionId": "debug-session",
                "runId": run_id,
                "hypothesisId": "H0",
                "location": "chat_service.process_chat:start",
                "message": "process_chat start",
                "data": {"user_id": req.user_id, "message": req.message},
                "timestamp": int(time.time() * 1000),
            }
        )
        # #endregion

        # Single embedding for routing
        query_embedding = await llm_service.generate_embedding(req.message)

        knowledge_sources, knowledge_best = await self.search_knowledge(
            query_text=req.message,
            query_embedding=query_embedding,
            limit=10,
            must_tags=None,
            boost_tags=None,
            run_id=run_id,
        )
        product_cards, product_best = await self.search_products(
            query_embedding=query_embedding,
            limit=10,
            run_id=run_id,
        )

        knowledge_strong = knowledge_best is not None and knowledge_best <= settings.KNOWLEDGE_DISTANCE_THRESHOLD
        product_strong = product_best is not None and product_best <= settings.PRODUCT_DISTANCE_THRESHOLD

        route = "none"
        reply_text = "I don't have enough information to answer that right now."
        sources = knowledge_sources
        product_carousel = product_cards

        if knowledge_strong and not product_strong:
            route = "knowledge"
            reply_text = await self.synthesize_answer(req.message, knowledge_sources)
            product_carousel = []
        elif product_strong and not knowledge_strong:
            route = "product"
            reply_text = "Here are some products that might help:"
            sources = []
        elif knowledge_strong and product_strong:
            route = "mixed"
            reply_text = await self.synthesize_answer(req.message, knowledge_sources)
        else:
            # Both weak -> keyword fallback
            fallback_sources = await self.keyword_fallback(req.message, limit=5)
            if fallback_sources:
                route = "fallback"
                sources = fallback_sources
                knowledge_sources = fallback_sources
                reply_text = await self.synthesize_answer(req.message, fallback_sources)
                product_carousel = []
            elif product_cards:
                route = "product"
                reply_text = "Here are some products that might help:"
                sources = []
            else:
                route = "none"
                reply_text = (
                    "I don't have enough information to answer that right now. "
                    "Please try asking in a different way."
                )

        # #region agent log
        _debug_log(
            {
                "sessionId": "debug-session",
                "runId": run_id,
                "hypothesisId": "HR",
                "location": "chat_service.process_chat:route_decision",
                "message": "routing decision",
                "data": {
                    "route": route,
                    "knowledge_best": knowledge_best,
                    "product_best": product_best,
                    "knowledge_threshold": settings.KNOWLEDGE_DISTANCE_THRESHOLD,
                    "product_threshold": settings.PRODUCT_DISTANCE_THRESHOLD,
                    "knowledge_count": len(knowledge_sources),
                    "product_count": len(product_cards),
                },
                "timestamp": int(time.time() * 1000),
            }
        )
        # #endregion

        logger.info(
            "chat_route decision",
            extra={
                "knowledge_best_distance": knowledge_best,
                "product_best_distance": product_best,
                "route": route,
            },
        )

        # persist messages
        await self.save_message(conversation.id, MessageRole.USER, req.message)
        await self.save_message(conversation.id, MessageRole.ASSISTANT, reply_text)

        return ChatResponse(
            conversation_id=conversation.id,
            reply_text=reply_text,
            product_carousel=product_carousel,
            follow_up_questions=[],
            intent="retrieval_router",
            sources=sources,
        )
