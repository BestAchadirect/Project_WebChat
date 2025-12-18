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
from app.services.rerank_service import rerank_service

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

    def _log_event(self, *, run_id: str, location: str, data: Dict[str, Any]) -> None:
        _debug_log(
            {
                "sessionId": "debug-session",
                "runId": run_id,
                "hypothesisId": "RAG",
                "location": location,
                "message": location,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }
        )

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

        logger.info(
            f"[RAG] knowledge retrieval: threshold={settings.KNOWLEDGE_DISTANCE_THRESHOLD} limit={limit} run_id={run_id}"
        )

        sources: List[KnowledgeSource] = []
        best_distance: Optional[float] = None

        for idx, row in enumerate(rows):
            (
                emb_id,
                chunk_text,
                article_id,
                chunk_id,
                title,
                category,
                url,
                distance,
                *maybe_boost,
            ) = row
            if best_distance is None:
                best_distance = float(distance)

            similarity = 1 - float(distance)

            if idx < 3:
                preview = (chunk_text or "")[:200].replace("\n", " ")
                logger.info(f"[RAG] top{idx+1} title={title!r} distance={float(distance):.4f} preview={preview!r}")

            sources.append(
                KnowledgeSource(
                    source_id=str(emb_id),
                    chunk_id=str(chunk_id) if chunk_id else None,
                    title=title,
                    content_snippet=(chunk_text or "")[: settings.RAG_MAX_CHUNK_CHARS_FOR_CONTEXT],
                    category=category,
                    relevance=similarity,
                    url=url,
                    distance=float(distance),
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
    ) -> Tuple[List[ProductCard], List[float], Optional[float]]:
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
            return [], [], None

        distances = [float(row.distance) for row in probe_rows]
        best_distance = distances[0] if distances else None
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
                                "distance": distances[idx] if idx < len(distances) else None,
                                "threshold": settings.PRODUCT_DISTANCE_THRESHOLD,
                            },
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                except Exception:
                    pass
            # #endregion

        return product_cards, distances[:5], best_distance

    async def _rerank_knowledge_with_cohere(
        self,
        *,
        query: str,
        candidates: List[KnowledgeSource],
        run_id: str,
    ) -> List[KnowledgeSource]:
        if not candidates:
            return []

        max_chars = settings.RAG_MAX_DOC_CHARS_FOR_RERANK
        documents: List[str] = []
        for c in candidates[: settings.RAG_RETRIEVE_TOPK_KNOWLEDGE]:
            doc = f"{c.title}\n{c.category or ''}\n{(c.content_snippet or '')[:max_chars]}"
            documents.append(doc[:max_chars])

        rerank_results = await rerank_service.rerank(
            query=query,
            documents=documents,
            top_n=settings.RAG_RERANK_TOPN,
            model=settings.RAG_COHERE_RERANK_MODEL,
        )

        if not rerank_results:
            # Skip or failure => keep original ordering
            self._log_event(
                run_id=run_id,
                location="chat_service.rag.rerank.cohere",
                data={"skipped_or_failed": True, "selected_ids": [c.source_id for c in candidates[: settings.RAG_RERANK_TOPN]]},
            )
            return candidates[: settings.RAG_RERANK_TOPN]

        # Rerank quality gate: if Cohere scores are near-zero, prefer distance ordering.
        top_scores = [float(r.relevance_score) for r in rerank_results[: settings.RAG_RERANK_TOPN]]
        above_count = sum(1 for s in top_scores if s >= settings.RAG_RERANK_MIN_SCORE)
        gate_fallback = above_count < settings.RAG_RERANK_MIN_SCORE_COUNT
        self._log_event(
            run_id=run_id,
            location="chat_service.rag.rerank.gate",
            data={
                "min_score": settings.RAG_RERANK_MIN_SCORE,
                "min_score_count": settings.RAG_RERANK_MIN_SCORE_COUNT,
                "above_count": above_count,
                "top_scores": top_scores,
                "decision": "fallback_to_distance" if gate_fallback else "accept_rerank",
            },
        )
        if gate_fallback:
            return candidates[: settings.RAG_RERANK_TOPN]

        selected: List[KnowledgeSource] = []
        top5 = []
        for r in rerank_results[: settings.RAG_RERANK_TOPN]:
            if 0 <= r.index < len(candidates):
                selected.append(candidates[r.index])
                top5.append({"source_id": candidates[r.index].source_id, "relevance_score": r.relevance_score})

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.rerank.cohere",
            data={"top": top5},
        )
        return selected

    async def _decompose_query(self, *, question: str, run_id: str) -> List[str]:
        """
        Decompose a complex user question into 4-8 focused sub-questions (strict JSON).
        Falls back to an empty list if decomposition fails.
        """
        system_prompt = (
            "You decompose a complex customer question into short, focused sub-questions that can be answered from a FAQ.\n"
            "Return STRICT JSON: {\"sub_questions\": [\"...\", ...]}.\n"
            "Rules:\n"
            "- 4 to 8 sub_questions\n"
            "- Each sub_question must be a standalone question\n"
            "- Avoid duplicates, keep them specific\n"
            "- Do NOT include any extra keys\n"
        )

        try:
            data = await llm_service.generate_chat_json(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                model=settings.RAG_DECOMPOSE_MODEL or settings.OPENAI_MODEL,
                temperature=0.0,
                max_tokens=300,
            )
            raw = data.get("sub_questions", [])
            if not isinstance(raw, list):
                raw = []
            sub_questions: List[str] = []
            seen: set[str] = set()
            for item in raw:
                if not isinstance(item, str):
                    continue
                q = item.strip()
                if not q:
                    continue
                key = q.lower()
                if key in seen:
                    continue
                seen.add(key)
                sub_questions.append(q)
                if len(sub_questions) >= settings.RAG_DECOMPOSE_MAX_SUBQUESTIONS:
                    break
        except Exception as e:
            sub_questions = []
            self._log_event(
                run_id=run_id,
                location="chat_service.rag.decompose",
                data={"error": str(e), "sub_questions": []},
            )
            return []

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.decompose",
            data={"sub_questions": sub_questions},
        )
        return sub_questions

    async def _retrieve_knowledge_for_query(
        self, *, query_text: str, run_id: str
    ) -> Tuple[List[KnowledgeSource], Optional[float]]:
        query_embedding = await llm_service.generate_embedding(query_text)
        sources, best = await self.search_knowledge(
            query_text=query_text,
            query_embedding=query_embedding,
            limit=settings.RAG_RETRIEVE_TOPK_KNOWLEDGE,
            must_tags=None,
            boost_tags=None,
            run_id=run_id,
        )
        if not sources:
            sources = await self.keyword_fallback(query_text, limit=settings.RAG_RETRIEVE_TOPK_KNOWLEDGE)
            best = None
        return sources, best

    async def _verify_answerable(
        self,
        *,
        question: str,
        knowledge_sources: List[KnowledgeSource],
        product_cards: List[ProductCard],
        run_id: str,
    ) -> Dict[str, Any]:
        verifier_model = settings.RAG_VERIFY_MODEL or settings.OPENAI_MODEL

        chunks_text = "\n\n".join(
            [
                (
                    f"ID: {s.source_id}\n"
                    f"TITLE: {s.title}\n"
                    f"CATEGORY: {s.category or ''}\n"
                    f"URL: {s.url or ''}\n"
                    f"TEXT: {(s.content_snippet or '')[: settings.RAG_MAX_CHUNK_CHARS_FOR_CONTEXT]}"
                )
                for s in knowledge_sources[: settings.RAG_RERANK_TOPN]
            ]
        )

        products_text = "\n".join(
            [
                f"- {p.name} (sku={p.sku}, price={p.price} {p.currency})"
                for p in product_cards[: min(5, len(product_cards))]
            ]
        )

        system_prompt = (
            "You are a strict verifier for a RAG chatbot. Decide if the provided context is sufficient to answer.\n"
            "Only say answerable=true if the context explicitly contains the needed information.\n"
            "Return STRICT JSON with keys:\n"
            "- answerable: bool\n"
            "- answer_type: \"knowledge\" | \"product\" | \"mixed\"\n"
            "- supporting_chunk_ids: list[str]\n"
            "- missing_info_question: string | null\n"
            "- answerable_parts: [{\"topic\": string, \"supporting_chunk_ids\": list[str]}]\n"
            "- missing_parts: [{\"topic\": string, \"missing_info_question\": string}]\n"
            "Rules:\n"
            "- supporting_chunk_ids must be a subset of the provided chunk IDs\n"
            "- answerable_parts/missing_parts should cover multi-topic questions\n"
            "- missing_parts should be ordered by priority (most important first)\n"
            "- If not fully answerable, still include any answerable_parts that are supported by the context\n"
        )

        user_prompt = (
            f"Question: {question}\n\n"
            f"Knowledge Chunks:\n{chunks_text or '[none]'}\n\n"
            f"Product Candidates:\n{products_text or '[none]'}\n"
        )

        try:
            decision = await llm_service.generate_chat_json(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=verifier_model,
                temperature=0.0,
                max_tokens=250,
            )
        except Exception as e:
            logger.error(f"Verifier failed: {e}")
            decision = {
                "answerable": False,
                "answer_type": "knowledge",
                "supporting_chunk_ids": [],
                "missing_info_question": None,
                "answerable_parts": [],
                "missing_parts": [],
            }

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.verify",
            data={"decision": decision},
        )
        return decision

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
                    source_id=str(chunk_id),
                    chunk_id=str(chunk_id),
                    title=title,
                    content_snippet=(chunk_text or "")[: settings.RAG_MAX_CHUNK_CHARS_FOR_CONTEXT],
                    category=category,
                    relevance=relevance,
                    url=url,
                    distance=None,
                )
            )
        return sources

    async def synthesize_answer(self, question: str, sources: List[KnowledgeSource]) -> str:
        if not sources:
            return (
                "I don't have enough information in my knowledge base to answer that yet. "
                "Try asking another question or rephrasing."
            )

        context = "\n\n".join(
            [
                f"ID: {s.source_id}\nTITLE: {s.title}\nTEXT: {s.content_snippet}"
                for s in sources[: min(5, len(sources))]
            ]
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant. Answer using ONLY the provided knowledge context. "
                    "If the answer is not in the context, say you don't have enough information. "
                    "Do not echo or restate the user's question."
                ),
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ]
        try:
            return await llm_service.generate_chat_response(messages, temperature=0.2)
        except Exception as e:
            logger.error(f"LLM response generation failed: {e}")
            return "I'm having trouble generating an answer right now. Please try again."

    async def synthesize_partial_answer(
        self,
        *,
        original_question: str,
        sources: List[KnowledgeSource],
        answerable_topics: List[str],
        missing_question: str,
    ) -> str:
        if not sources:
            return missing_question

        topics_text = ", ".join(answerable_topics[:6]) if answerable_topics else "the supported parts"
        context = "\n\n".join(
            [
                f"ID: {s.source_id}\nTITLE: {s.title}\nURL: {s.url or ''}\nTEXT: {s.content_snippet}"
                for s in sources[: min(6, len(sources))]
            ]
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a careful RAG assistant. Write ONLY what is explicitly supported by the context.\n"
                    "If a detail is not in the context, say it is not specified.\n"
                    "Do not invent policies.\n"
                    "Do not echo the user's question.\n"
                    "Output a short section titled 'What I found' with 2-6 bullet points."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original question:\n{original_question}\n\n"
                    f"Focus topics:\n{topics_text}\n\n"
                    f"Context:\n{context}\n"
                ),
            },
        ]

        try:
            found = await llm_service.generate_chat_response(messages, temperature=0.2)
        except Exception as e:
            logger.error(f"Partial answer generation failed: {e}")
            found = "What I found:\n- I couldn't generate a summary from the retrieved context."

        return f"{found}\n\nOne question to confirm:\n{missing_question}"

    async def process_chat(self, req: ChatRequest) -> ChatResponse:
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        _history = await self.get_history(conversation.id)

        run_id = f"chat-{int(time.time() * 1000)}"

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

        sub_questions = await self._decompose_query(question=req.message, run_id=run_id)
        queries = [req.message] + sub_questions
        # De-dup while preserving order
        seen_q: set[str] = set()
        queries = [q for q in queries if not (q.lower() in seen_q or seen_q.add(q.lower()))]

        merged_by_key: Dict[str, KnowledgeSource] = {}
        per_query_best: List[Optional[float]] = []

        for q in queries:
            sources_q, best_q = await self._retrieve_knowledge_for_query(query_text=q, run_id=run_id)
            per_query_best.append(best_q)
            selected_q = await self._rerank_knowledge_with_cohere(query=q, candidates=sources_q, run_id=run_id)
            for s in selected_q:
                key = s.chunk_id or s.source_id
                existing = merged_by_key.get(key)
                if existing is None:
                    merged_by_key[key] = s
                    continue
                # Keep the candidate with the better (lower) distance if available
                if s.distance is not None and (existing.distance is None or s.distance < existing.distance):
                    merged_by_key[key] = s

        knowledge_sources = sorted(
            merged_by_key.values(),
            key=lambda s: (s.distance is None, s.distance if s.distance is not None else 9999.0),
        )
        knowledge_sources = knowledge_sources[: settings.RAG_RETRIEVE_TOPK_KNOWLEDGE]
        knowledge_best = min([d for d in per_query_best if d is not None], default=None)

        # Single embedding for product retrieval (original question)
        query_embedding = await llm_service.generate_embedding(req.message)
        product_cards, product_top_distances, product_best = await self.search_products(
            query_embedding=query_embedding,
            limit=settings.RAG_RETRIEVE_TOPK_PRODUCT,
            run_id=run_id,
        )

        knowledge_top_distances = [s.distance for s in knowledge_sources[:5] if s.distance is not None]

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.retrieve",
            data={
                "knowledge_best": knowledge_best,
                "product_best": product_best,
                "knowledge_top5_distances": knowledge_top_distances,
                "product_top5_distances": product_top_distances,
                "knowledge_count": len(knowledge_sources),
                "product_count": len(product_cards),
                "decompose_used": bool(sub_questions),
                "sub_questions_count": len(sub_questions),
            },
        )

        reranked_knowledge = knowledge_sources[: settings.RAG_RERANK_TOPN]

        decision = await self._verify_answerable(
            question=req.message,
            knowledge_sources=reranked_knowledge,
            product_cards=product_cards,
            run_id=run_id,
        )

        answerable = bool(decision.get("answerable"))
        answer_type = (decision.get("answer_type") or "knowledge").lower()
        supporting_ids = [str(x) for x in (decision.get("supporting_chunk_ids") or [])]
        missing_q = decision.get("missing_info_question")
        answerable_parts = decision.get("answerable_parts") or []
        missing_parts = decision.get("missing_parts") or []

        answerable_topics: List[str] = []
        part_supporting_ids: List[str] = []
        if isinstance(answerable_parts, list):
            for p in answerable_parts:
                if isinstance(p, dict):
                    topic = p.get("topic")
                    if isinstance(topic, str) and topic.strip():
                        answerable_topics.append(topic.strip())
                    ids = p.get("supporting_chunk_ids") or []
                    if isinstance(ids, list):
                        part_supporting_ids.extend([str(x) for x in ids])

        missing_parts_q: Optional[str] = None
        if isinstance(missing_parts, list) and missing_parts:
            first = missing_parts[0]
            if isinstance(first, dict):
                mq = first.get("missing_info_question")
                if isinstance(mq, str) and mq.strip():
                    missing_parts_q = mq.strip()

        selected_sources = reranked_knowledge
        effective_supporting_ids = part_supporting_ids or supporting_ids
        if effective_supporting_ids:
            by_id = {s.source_id: s for s in reranked_knowledge}
            selected_sources = [by_id[sid] for sid in effective_supporting_ids if sid in by_id] or reranked_knowledge

        route = "clarify"
        reply_text = ""
        sources: List[KnowledgeSource] = []
        product_carousel: List[ProductCard] = []

        if answerable:
            if answer_type == "product":
                route = "product"
                reply_text = "Here are some products that might help:"
                product_carousel = product_cards
                sources = []
            elif answer_type == "mixed":
                route = "mixed"
                reply_text = await self.synthesize_answer(req.message, selected_sources)
                product_carousel = product_cards
                sources = selected_sources
            else:
                route = "knowledge"
                reply_text = await self.synthesize_answer(req.message, selected_sources)
                product_carousel = []
                sources = selected_sources
        else:
            route = "clarify"
            clarifier = missing_parts_q or (missing_q.strip() if isinstance(missing_q, str) else "")
            if selected_sources and effective_supporting_ids and clarifier:
                reply_text = await self.synthesize_partial_answer(
                    original_question=req.message,
                    sources=selected_sources,
                    answerable_topics=answerable_topics,
                    missing_question=clarifier,
                )
                sources = selected_sources
            elif clarifier:
                reply_text = clarifier
                sources = []
            else:
                reply_text = "Could you clarify what exactly you want to know (one detail)?"
                sources = []
            product_carousel = []

        if sources:
            citations = "\n".join(
                f"- {s.title}{f' ({s.url})' if s.url else ''}" for s in sources[:5]
            )
            reply_text = f"{reply_text}\n\nSources:\n{citations}"

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.route_decision",
            data={
                "route": route,
                "answerable": answerable,
                "answer_type": answer_type,
                "knowledge_best": knowledge_best,
                "product_best": product_best,
                "knowledge_threshold_observed": settings.KNOWLEDGE_DISTANCE_THRESHOLD,
                "product_threshold_observed": settings.PRODUCT_DISTANCE_THRESHOLD,
                "selected_source_ids": [s.source_id for s in sources[:5]],
            },
        )

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
            intent=route,
            sources=sources,
        )
