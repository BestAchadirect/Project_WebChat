from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.schemas.chat import ChatContext, KnowledgeSource
from app.services.knowledge.retrieval import KnowledgeRetrievalService


class KnowledgeContextAssembler:
    def __init__(self, retrieval_service: KnowledgeRetrievalService):
        self._retrieval_service = retrieval_service

    async def fetch_sources(
        self,
        *,
        use_knowledge: bool,
        search_query: str,
        query_embedding: Optional[List[float]],
        ctx: ChatContext,
        is_complex: bool,
        is_question_like: bool,
        is_policy_intent: bool,
        policy_topic_count: int,
        max_sub_questions: int,
        run_id: str,
    ) -> Tuple[List[KnowledgeSource], Dict[str, Any]]:
        if not use_knowledge or query_embedding is None:
            return [], {}

        debug_meta: Dict[str, Any] = {}
        if is_policy_intent or is_complex:
            knowledge_result = await self._retrieval_service.retrieve(
                ctx=ctx,
                knowledge_query_text=search_query,
                knowledge_embedding=query_embedding,
                is_complex=is_complex,
                is_question_like=is_question_like,
                is_policy_intent=is_policy_intent,
                policy_topic_count=policy_topic_count,
                max_sub_questions=max_sub_questions,
                run_id=run_id,
            )
            debug_meta["knowledge_decompose_used"] = knowledge_result.decomposition_used
            debug_meta["knowledge_decompose_reason"] = knowledge_result.decomposition_reason
            return knowledge_result.knowledge_sources, debug_meta

        sources = await self._retrieval_service.search(
            query_text=search_query,
            query_embedding=query_embedding,
            limit=5,
            run_id=run_id,
        )
        return sources, debug_meta
