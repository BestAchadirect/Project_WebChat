from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.schemas.chat import ChatResponse, KnowledgeSource
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.retrieval.retrieval_outcome import RetrievalOutcome
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities
from app.services.chat.runtime.grounding import GroundingDecision
from app.services.chat.runtime.search_plan import SearchPlan
from app.services.chat.routing.contracts import WorkflowResult


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
class PipelinePresentationState:
    selected_components: List[ComponentType] = field(default_factory=list)
    canonical_products: List[Any] = field(default_factory=list)


@dataclass
class PipelineKnowledgeState:
    sources: List[KnowledgeSource] = field(default_factory=list)
    answer: str = ""
    error_message: str = ""


@dataclass
class PipelineCatalogState:
    product_ids: List[Any] = field(default_factory=list)
    query_product_ids: List[Any] = field(default_factory=list)
    query_embedding: Optional[List[float]] = None
    handled_attribute_list: bool = False
    attribute_list_target: str = ""
    semantic_search_done: bool = False
    query_cache_key: str = ""
    pagination_requested: bool = False
    pagination_offset: int = 0
    pagination_limit: int = 0
    pagination_has_more: bool = False


@dataclass
class PipelineRetrievalState:
    result_count: int = 0
    source: ComponentSource = ComponentSource.ERROR
    outcome: Optional[RetrievalOutcome] = None


@dataclass
class PipelineDecisionRuntimeState:
    runtime_capabilities: Optional[ChatRuntimeCapabilities] = None
    search_plan: Optional[SearchPlan] = None
    grounding_decision: Optional[GroundingDecision] = None
    knowledge_grounding_decision: Optional[GroundingDecision] = None
    ambiguity_reason: Optional[str] = None
    internal_workflow: str = ""
    intent: str = ""
    subintent: str = ""
    user_goal: str = ""
    product_query: str = ""
    response_policy: str = ""
    clarify_question: str = ""
    pending_task_type: str = ""
    missing_slot: str = ""
    intent_confidence: float = 0.0
    retrieval_confidence: float = 0.0
    answerability: str = "none"
    verification_reason: str = ""
    workflow_result: Optional[WorkflowResult] = None


@dataclass
class PipelineWorkflowState:
    presentation: PipelinePresentationState = field(default_factory=PipelinePresentationState)
    knowledge: PipelineKnowledgeState = field(default_factory=PipelineKnowledgeState)
    catalog: PipelineCatalogState = field(default_factory=PipelineCatalogState)
    retrieval: PipelineRetrievalState = field(default_factory=PipelineRetrievalState)
    decision: PipelineDecisionRuntimeState = field(default_factory=PipelineDecisionRuntimeState)
