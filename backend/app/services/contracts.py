from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from app.schemas.chat import ChatContext, KnowledgeSource, ProductCard


class CatalogProductSearchService(Protocol):
    async def vector_search(
        self,
        *,
        query_embedding: List[float],
        limit: int = 10,
        candidate_limit: Optional[int] = None,
        candidate_multiplier: int = 3,
    ) -> Tuple[List[ProductCard], List[float], Optional[float], Dict[str, float]]:
        ...

    async def smart_search(
        self,
        *,
        query_embedding: List[float],
        candidates: Sequence[str],
        limit: int = 10,
    ) -> Tuple[List[ProductCard], List[float], Optional[float], Dict[str, float]]:
        ...

    async def get_product_by_sku(self, sku: str) -> Optional[ProductCard]:
        ...

    async def get_inventory_snapshot(self, sku: str) -> Dict[str, Any]:
        ...


class KnowledgeRetrievalService(Protocol):
    async def search(
        self,
        *,
        query_text: str,
        query_embedding: List[float],
        limit: int = 5,
        category: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> List[KnowledgeSource]:
        ...

    async def retrieve(
        self,
        *,
        ctx: ChatContext,
        knowledge_query_text: str,
        knowledge_embedding: List[float],
        is_complex: bool,
        is_question_like: bool,
        is_policy_intent: bool,
        policy_topic_count: int,
        max_sub_questions: int,
        run_id: Optional[str] = None,
    ) -> Any:
        ...


class ChatOrchestratorService(Protocol):
    async def process_chat(self, req: Any, channel: Optional[str] = None) -> Any:
        ...


class ImportProductsPipeline(Protocol):
    async def import_products(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        ...


class ImportKnowledgePipeline(Protocol):
    async def import_knowledge(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        ...
