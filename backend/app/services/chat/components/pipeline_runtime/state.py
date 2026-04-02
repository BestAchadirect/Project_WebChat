from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.schemas.chat import ChatResponse, KnowledgeSource
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.retrieval.retrieval_outcome import RetrievalOutcome
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities


@dataclass
class ComponentPipelineResult:
    response: ChatResponse
    detail_mode_triggered: bool
    llm_calls: int
    embedding_calls: int
    external_call_counts: Dict[str, int] = field(default_factory=dict)
    spans: Dict[str, float] = field(default_factory=dict)
    debug: Dict[str, Any] = field(default_factory=dict)
    conversation_state: Optional[Dict[str, Any]] = None


@dataclass
class PipelineExecutionState:
    debug_meta: Dict[str, Any]
    spans: Dict[str, float]
    external_call_counts: Dict[str, int]


@dataclass
class PipelineWorkflowState:
    selected_components: List[ComponentType] = field(default_factory=list)
    canonical_products: List[Any] = field(default_factory=list)
    recommendations: List[Any] = field(default_factory=list)
    knowledge_sources: List[KnowledgeSource] = field(default_factory=list)
    knowledge_answer: str = ""
    result_count: int = 0
    product_ids: List[Any] = field(default_factory=list)
    query_product_ids: List[Any] = field(default_factory=list)
    query_embedding: Optional[List[float]] = None
    retrieval_source: ComponentSource = ComponentSource.ERROR
    retrieval_outcome: Optional[RetrievalOutcome] = None
    runtime_capabilities: Optional[ChatRuntimeCapabilities] = None
    ambiguity_reason: Optional[str] = None
    knowledge_error_message: str = ""
    handled_attribute_list: bool = False
    attribute_list_target: str = ""
    semantic_catalog_search_done: bool = False
    query_cache_key: str = ""
    pagination_requested: bool = False
    pagination_offset: int = 0
    pagination_limit: int = 0
    pagination_has_more: bool = False
