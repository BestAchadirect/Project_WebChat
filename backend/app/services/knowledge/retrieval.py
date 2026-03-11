from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import ChatContext, KnowledgeSource
from app.services.knowledge.pipeline import KnowledgePipeline


def _no_op_log_event(*_: Any, **__: Any) -> None:
    return


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
        store_overview_request: bool = False,
        run_id: Optional[str] = None,
    ) -> List[KnowledgeSource]:
        sources, _best = await self._pipeline.search_knowledge(
            query_text=query_text,
            query_embedding=query_embedding,
            limit=limit,
            store_overview_request=store_overview_request,
            run_id=run_id,
        )
        if not category:
            return sources
        wanted = category.strip().lower()
        if not wanted:
            return sources
        return [source for source in sources if (source.category or "").strip().lower() == wanted]

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
