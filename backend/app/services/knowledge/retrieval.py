from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import ChatContext, KnowledgeSource
from app.services.knowledge.pipeline import KnowledgePipeline


def _no_op_log_event(*_: Any, **__: Any) -> None:
    return


def _normalize_category(value: Optional[str]) -> str:
    return " ".join(str(value or "").strip().lower().split())


class KnowledgeRetrievalService:
    """Stable facade for knowledge retrieval used by chat and agentic flows."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        log_event: Optional[Callable[..., None]] = None,
    ):
        self._pipeline = KnowledgePipeline(db=db, log_event=log_event or _no_op_log_event)

    async def search(
        self,
        *,
        query_text: str,
        query_embedding: List[float],
        limit: int = 5,
        category: Optional[str] = None,
        must_tags: Optional[List[str]] = None,
        boost_tags: Optional[List[str]] = None,
        store_overview_request: bool = False,
        run_id: Optional[str] = None,
    ) -> List[KnowledgeSource]:
        requested_limit = max(1, int(limit))
        wanted_category = _normalize_category(category)
        search_limit = requested_limit
        if wanted_category:
            search_limit = max(requested_limit * 3, requested_limit, 10)
        sources, _best = await self._pipeline.search_knowledge(
            query_text=query_text,
            query_embedding=query_embedding,
            limit=search_limit,
            must_tags=must_tags,
            boost_tags=boost_tags,
            store_overview_request=store_overview_request,
            run_id=run_id,
        )
        normalized_sources = sorted(
            list(sources or []),
            key=lambda source: (
                -float(getattr(source, "relevance", 0.0) or 0.0),
                str(getattr(source, "title", "") or "").strip().lower(),
                str(getattr(source, "source_id", "") or "").strip().lower(),
            ),
        )
        if not wanted_category:
            return normalized_sources[:requested_limit]
        filtered = [
            source
            for source in normalized_sources
            if _normalize_category(getattr(source, "category", None)) == wanted_category
        ]
        return filtered[:requested_limit]

    async def retrieve(
        self,
        *,
        ctx: ChatContext,
        knowledge_query_text: str,
        knowledge_embedding: List[float],
        is_complex: bool,
        is_question_like: bool,
        is_policy_like: bool,
        policy_topic_count: int,
        max_sub_questions: int,
        store_overview_request: bool = False,
        run_id: Optional[str] = None,
    ) -> Any:
        return await self._pipeline.retrieve(
            ctx=ctx,
            knowledge_query_text=knowledge_query_text,
            knowledge_embedding=knowledge_embedding,
            is_complex=is_complex,
            is_question_like=is_question_like,
            is_policy_like=is_policy_like,
            policy_topic_count=policy_topic_count,
            max_sub_questions=max_sub_questions,
            store_overview_request=store_overview_request,
            run_id=run_id,
        )
