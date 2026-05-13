from __future__ import annotations

from types import SimpleNamespace

from app.services.chat.components.pipeline_runtime.workflow_catalog import PipelineWorkflowCatalogMixin
from app.services.chat.components.types import ComponentType


def test_structured_no_match_with_filters_returns_answer_component() -> None:
    detail = SimpleNamespace(attribute_filters={"category": "sterilized", "color": "opal"})

    components = PipelineWorkflowCatalogMixin._select_catalog_components(
        text="Can I see sterilization with opal?",
        workflow="catalog",
        detail=detail,
        product_ids=[],
        ambiguity_reason="structured_no_match",
    )

    assert components == [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]


def test_structured_no_match_with_candidate_ids_returns_product_cards() -> None:
    detail = SimpleNamespace(attribute_filters={"category": "sterilized", "color": "opal"})

    components = PipelineWorkflowCatalogMixin._select_catalog_components(
        text="Can I see sterilization with opal?",
        workflow="catalog",
        detail=detail,
        product_ids=["product-1"],
        ambiguity_reason="structured_no_match",
    )

    assert components == [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]


def test_structured_no_match_reply_summarizes_all_filters() -> None:
    reply = PipelineWorkflowCatalogMixin._build_structured_no_match_reply(
        attribute_filters={"category": "sterilized;;opal body jewelry", "color": "clear opal"},
    )

    assert "exact match for that request" in reply
    assert "similar products" in reply
    assert "broaden the search" in reply
