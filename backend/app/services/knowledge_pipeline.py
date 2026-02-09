from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import case, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.knowledge import KnowledgeArticle, KnowledgeChunk, KnowledgeChunkTag, KnowledgeEmbedding
from app.schemas.chat import ChatContext, KnowledgeSource
from app.services.llm_service import llm_service
from app.utils.debug_log import debug_log as _debug_log

LogEventFn = Callable[..., None]

logger = get_logger(__name__)


@dataclass
class KnowledgeRetrievalResult:
    knowledge_sources: List[KnowledgeSource]
    knowledge_best: Optional[float]
    knowledge_top_distances: List[float]
    sub_questions: List[str]
    per_query_keep: int
    decomposition_used: bool
    decomposition_reason: str
    decomposition_knowledge_best: Optional[float]
    decomposition_gap: Optional[float]


class KnowledgePipeline:
    def __init__(
        self,
        *,
        db: AsyncSession,
        log_event: LogEventFn,
    ) -> None:
        self.db = db
        self._log_event = log_event

    async def search_knowledge(
        self,
        query_text: str,
        query_embedding: List[float],
        limit: int = 10,
        must_tags: Optional[List[str]] = None,
        boost_tags: Optional[List[str]] = None,
        run_id: Optional[str] = None,
    ) -> Tuple[List[KnowledgeSource], Optional[float]]:
        tag_join_needed = bool(must_tags or boost_tags)

        distance_col = KnowledgeEmbedding.embedding.cosine_distance(query_embedding).label("distance")
        model = getattr(settings, "KNOWLEDGE_EMBEDDING_MODEL", settings.EMBEDDING_MODEL)

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
        stmt = stmt.where(or_(KnowledgeEmbedding.model.is_(None), KnowledgeEmbedding.model == model))

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

        return sources, best_distance

    async def _decompose_query(self, *, question: str, run_id: str) -> List[str]:
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
                usage_kind="rag_decompose",
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
        return sources, best

    def _distance_stats(
        self, sources: List[KnowledgeSource]
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        distances = [float(s.distance) for s in sources if s.distance is not None]
        if not distances:
            return None, None, None
        d1 = distances[0]
        d10 = distances[9] if len(distances) >= 10 else None
        gap = (d10 - d1) if (d10 is not None and d1 is not None) else None
        return d1, d10, gap

    async def retrieve(
        self,
        *,
        ctx: ChatContext,
        knowledge_query_text: str,
        knowledge_embedding: Optional[List[float]],
        is_complex: bool,
        is_question_like: bool,
        is_policy_intent: bool,
        policy_topic_count: int,
        max_sub_questions: int,
        run_id: str,
    ) -> KnowledgeRetrievalResult:
        knowledge_sources_primary, knowledge_best_primary = await self.search_knowledge(
            query_text=knowledge_query_text,
            query_embedding=knowledge_embedding or [],
            limit=settings.RAG_RETRIEVE_TOPK_KNOWLEDGE,
            must_tags=None,
            boost_tags=None,
            run_id=run_id,
        )

        d1_primary, d10_primary, gap_primary = self._distance_stats(knowledge_sources_primary)
        decompose_weak_thr = float(getattr(settings, "RAG_DECOMPOSE_WEAK_DISTANCE", 0.55))
        decompose_gap_thr = float(getattr(settings, "RAG_DECOMPOSE_GAP_THRESHOLD", 0.06))
        policy_like = bool(is_policy_intent or policy_topic_count >= 2)
        weak_retrieval = (knowledge_best_primary is None) or (
            float(knowledge_best_primary) >= decompose_weak_thr
        )
        ambiguous_retrieval = gap_primary is not None and gap_primary < decompose_gap_thr
        should_decompose = bool(
            is_complex and is_question_like and policy_like and (weak_retrieval or ambiguous_retrieval)
        )
        if not is_question_like:
            decompose_reason = "not_question_like"
        elif not policy_like:
            decompose_reason = "not_policy_like"
        elif not is_complex:
            decompose_reason = "not_complex"
        elif not (weak_retrieval or ambiguous_retrieval):
            decompose_reason = "confident_retrieval"
        else:
            reasons: List[str] = []
            if weak_retrieval:
                reasons.append("weak_distance")
            if ambiguous_retrieval:
                reasons.append("ambiguous_gap")
            decompose_reason = "+".join(reasons) if reasons else "weak_or_ambiguous"

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.decompose.gate",
            data={
                "should_decompose": should_decompose,
                "reason": decompose_reason,
                "is_complex": is_complex,
                "is_question_like": is_question_like,
                "policy_like": policy_like,
                "policy_topic_count": policy_topic_count,
                "knowledge_best": knowledge_best_primary,
                "d1": d1_primary,
                "d10": d10_primary,
                "gap": gap_primary,
                "weak_threshold": decompose_weak_thr,
                "gap_threshold": decompose_gap_thr,
            },
        )

        sub_questions: List[str] = []
        if should_decompose:
            sub_questions = await self._decompose_query(question=knowledge_query_text, run_id=run_id)
            sub_questions = sub_questions[:max_sub_questions]
        queries = [knowledge_query_text] + sub_questions
        seen_q: set[str] = set()
        queries = [q for q in queries if not (q.lower() in seen_q or seen_q.add(q.lower()))]

        def _choose_better(existing: Optional[KnowledgeSource], new: KnowledgeSource) -> KnowledgeSource:
            if existing is None:
                return new
            if existing.distance is None and new.distance is None:
                chosen = existing
            elif existing.distance is None and new.distance is not None:
                chosen = new
            elif existing.distance is not None and new.distance is None:
                chosen = existing
            else:
                chosen = new if new.distance < existing.distance else existing

            other = new if chosen is existing else existing
            if getattr(chosen, "query_hint", None) is None and getattr(other, "query_hint", None) is not None:
                chosen.query_hint = other.query_hint
            return chosen

        per_query_keep = max(1, int(getattr(settings, "RAG_PER_QUERY_KEEP", 1)))
        coverage_by_key: Dict[str, KnowledgeSource] = {}
        coverage_keys_in_order: List[str] = []
        pool_by_key: Dict[str, KnowledgeSource] = {}
        kept_per_query: List[Dict[str, Any]] = []
        per_query_best: List[Optional[float]] = []

        for q in queries:
            if q == knowledge_query_text:
                sources_q = knowledge_sources_primary
                best_q = knowledge_best_primary
            else:
                sources_q, best_q = await self._retrieve_knowledge_for_query(query_text=q, run_id=run_id)
            per_query_best.append(best_q)
            kept_ids: List[str] = []
            for s in sources_q[:per_query_keep]:
                s.query_hint = q
                key = s.chunk_id or s.source_id
                if key not in coverage_by_key:
                    coverage_keys_in_order.append(key)
                coverage_by_key[key] = _choose_better(coverage_by_key.get(key), s)
                kept_ids.append(str(s.source_id))

            kept_per_query.append({"query": q, "kept_source_ids": kept_ids})

            for s in sources_q[per_query_keep:]:
                s.query_hint = q
                key = s.chunk_id or s.source_id
                if key in coverage_by_key:
                    continue
                pool_by_key[key] = _choose_better(pool_by_key.get(key), s)

        coverage_sources: List[KnowledgeSource] = [
            coverage_by_key[k] for k in coverage_keys_in_order if k in coverage_by_key
        ]
        pool_sources = sorted(
            pool_by_key.values(),
            key=lambda s: (s.distance is None, s.distance if s.distance is not None else 9999.0),
        )

        merged: List[KnowledgeSource] = []
        merged_keys: set[str] = set()
        for s in coverage_sources:
            key = s.chunk_id or s.source_id
            if key in merged_keys:
                continue
            merged.append(s)
            merged_keys.add(key)

        for s in pool_sources:
            if len(merged) >= settings.RAG_RETRIEVE_TOPK_KNOWLEDGE:
                break
            key = s.chunk_id or s.source_id
            if key in merged_keys:
                continue
            merged.append(s)
            merged_keys.add(key)

        knowledge_sources = merged
        knowledge_best = min([d for d in per_query_best if d is not None], default=None)
        knowledge_top_distances = [s.distance for s in knowledge_sources[:5] if s.distance is not None]

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.merge.coverage",
            data={"kept_per_query": kept_per_query, "coverage_count": len(coverage_sources)},
        )

        return KnowledgeRetrievalResult(
            knowledge_sources=knowledge_sources,
            knowledge_best=knowledge_best,
            knowledge_top_distances=knowledge_top_distances,
            sub_questions=sub_questions,
            per_query_keep=per_query_keep,
            decomposition_used=should_decompose,
            decomposition_reason=decompose_reason,
            decomposition_knowledge_best=knowledge_best_primary,
            decomposition_gap=gap_primary,
        )
