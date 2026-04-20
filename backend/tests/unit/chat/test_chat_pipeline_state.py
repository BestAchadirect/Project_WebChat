from __future__ import annotations

from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.types import ComponentSource, ComponentType


def test_pipeline_workflow_state_exposes_nested_substates() -> None:
    state = PipelineWorkflowState()

    state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
    state.catalog.product_ids = ["p1", "p2"]
    state.knowledge.answer = "answer"
    state.decision.ambiguity_reason = "routing_fallback"
    state.retrieval.source = ComponentSource.KNOWLEDGE
    state.retrieval.result_count = 2

    assert state.presentation.selected_components == [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
    assert state.catalog.product_ids == ["p1", "p2"]
    assert state.knowledge.answer == "answer"
    assert state.decision.ambiguity_reason == "routing_fallback"
    assert state.retrieval.source == ComponentSource.KNOWLEDGE
    assert state.retrieval.result_count == 2


def test_pipeline_workflow_state_compatibility_properties_reflect_nested_updates() -> None:
    state = PipelineWorkflowState()

    state.catalog.pagination_requested = True
    state.catalog.pagination_limit = 24
    state.knowledge.sources = []
    state.presentation.canonical_products = ["card-1"]
    state.decision.answerability = "partial"

    assert state.catalog.pagination_requested is True
    assert state.catalog.pagination_limit == 24
    assert state.knowledge.sources == []
    assert state.presentation.canonical_products == ["card-1"]
    assert state.decision.answerability == "partial"
