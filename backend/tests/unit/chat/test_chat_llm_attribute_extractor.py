from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.ai.llm_service import llm_service
from app.services.chat.parsing.llm_attribute_extractor import (
    classify_chat_surface_intent,
    enrich_product_attribute_filters,
    infer_attribute_list_target,
    infer_chat_interpretation,
    infer_detail_query,
)
from app.services.chat.parsing.parser_rule_types import build_rule_set


def _rules():
    return build_rule_set(
        requested_field_patterns={},
        value_extract_patterns={},
        detection_attribute_order=["finish", "category"],
        allowed_attribute_filters=["finish", "category", "material", "gauge", "threading", "jewelry_type"],
    )


def _understanding_payload(
    workflow_hypothesis: str,
    *,
    reason: str,
    confidence: float = 0.9,
    needs_products: bool = False,
    needs_knowledge: bool = False,
    knowledge_query: str = "",
    store_overview_request: bool = False,
    **hints: Any,
) -> dict[str, Any]:
    return {
        "workflow_hypothesis": workflow_hypothesis,
        "needs_products": needs_products,
        "needs_knowledge": needs_knowledge,
        "store_overview_request": store_overview_request,
        "knowledge_query": knowledge_query,
        "reason": reason,
        "confidence": confidence,
        **hints,
    }


@pytest.mark.asyncio
async def test_enrich_product_attribute_filters_returns_validated_exact_filters_and_semantic_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_validate(db, *, filters, alias_map, allowed_attributes):
        if dict(filters or {}) == {"gauge": "16g"}:
            return {"gauge": "16g"}
        return {}

    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        return {
            "exact_filters": {
                "gauge": "16g",
            },
            "soft_filters": {
                "material": "titanium",
                "jewelry_type": "barbell",
            },
            "semantic_hints": ["sterilization"],
            "clarify_focus": "condition",
            "confidence": 0.91,
        }

    monkeypatch.setattr(
        "app.services.chat.parsing.llm_attribute_extractor._validate_attribute_filters",
        fake_validate,
    )
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await enrich_product_attribute_filters(
        db=SimpleNamespace(execute=object()),
        user_text="I want sterilization in 16g",
        workflow="catalog",
        existing_filters={},
        alias_map={"finish": {"sterilization": "sterilized"}},
        parser_rules=_rules(),
    )

    assert result.exact_filters == {"gauge": "16g"}
    assert result.soft_filters == {"material": "titanium", "jewelry_type": "barbell"}
    assert result.semantic_hints == ["sterilization"]
    assert result.clarify_focus == "condition"
    assert result.confidence == pytest.approx(0.91)
    assert result.llm_call_count == 1
    assert result.debug["llm_attribute_interpretation_used"] is True
    assert result.debug["llm_exact_filter_keys"] == ["gauge"]
    assert result.debug["llm_soft_filter_keys"] == ["material", "jewelry_type"]
    assert result.debug["semantic_hint_keys"] == ["sterilization"]
    assert result.debug["semantic_hint_clarify_focus"] == "condition"


@pytest.mark.asyncio
async def test_enrich_product_attribute_filters_returns_empty_outputs_when_llm_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_generate_chat_json(*args, **kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(llm_service, "generate_chat_json", failing_generate_chat_json)

    result = await enrich_product_attribute_filters(
        db=object(),
        user_text="I want sterilization product",
        workflow="catalog",
        existing_filters={},
        alias_map={},
        parser_rules=_rules(),
    )

    assert result.exact_filters == {}
    assert result.soft_filters == {}
    assert result.semantic_hints == []
    assert result.clarify_focus == ""
    assert result.llm_call_count == 0
    assert result.debug["semantic_hint_source"] == ""


@pytest.mark.asyncio
async def test_infer_detail_query_does_not_force_clarify_when_llm_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_generate_chat_json(*args, **kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(llm_service, "generate_chat_json", failing_generate_chat_json)

    result = await infer_detail_query(
        user_text="Show me titanium jewelry",
        workflow="catalog",
        alias_map={},
        parser_rules=_rules(),
        existing_filters={},
    )

    assert result.attribute_filters == {}
    assert result.semantic_hints == []
    assert result.clarify_focus == ""
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_infer_attribute_list_target_returns_supported_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        return {
            "target": "presentation type",
            "confidence": 0.88,
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_attribute_list_target(
        user_text="What presentation type options do you have?",
        workflow="catalog",
    )

    assert result.target == "presentation_type"
    assert result.confidence == pytest.approx(0.88)
    assert result.llm_call_count == 1
    assert result.debug["llm_attribute_list_target_used"] is True
    assert result.debug["llm_attribute_list_target_value"] == "presentation_type"


@pytest.mark.asyncio
async def test_classify_chat_surface_intent_prefers_support_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(*args, **kwargs):
        assert kwargs.get("usage_kind") == "chat_understanding"
        return _understanding_payload(
            "company_info",
            reason="support contact request",
            confidence=0.95,
            needs_knowledge=True,
            knowledge_query="how can I contact customer service",
            knowledge_tags=["contact"],
        )

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await classify_chat_surface_intent(
        user_text="I want to talk to a sale person",
        locale="en-US",
        channel="widget",
    )

    assert result.intent_family == "support_contact"
    assert result.knowledge_query == "how can I contact customer service"
    assert result.reason == "support contact request"
    assert result.confidence == pytest.approx(0.95)
    assert result.llm_call_count == 1


@pytest.mark.asyncio
async def test_classify_chat_surface_intent_uses_llm_for_ambiguous_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {"count": 0}

    async def fake_generate_chat_json(*args, **kwargs):
        calls["count"] += 1
        return {
            "workflow_hypothesis": "off_topic",
            "needs_products": False,
            "needs_knowledge": False,
            "store_overview_request": False,
            "knowledge_query": "",
            "reason": "unrelated request",
            "confidence": 0.84,
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await classify_chat_surface_intent(
        user_text="I need help with something on the site.",
        locale="en-US",
        channel="widget",
    )

    assert calls["count"] == 1
    assert result.intent_family == "off_topic"
    assert result.reason == "unrelated request"
    assert result.confidence == pytest.approx(0.84)
    assert result.llm_call_count == 1


@pytest.mark.asyncio
async def test_classify_chat_surface_intent_detects_company_question_without_vector_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(*args, **kwargs):
        assert kwargs.get("usage_kind") == "chat_understanding"
        return _understanding_payload(
            "company_info",
            reason="company question",
            confidence=0.95,
            needs_knowledge=True,
            knowledge_query="where is your company located",
            store_overview_request=True,
        )

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await classify_chat_surface_intent(
        user_text="Where is the company?",
        locale="en-US",
        channel="widget",
    )

    assert result.intent_family == "knowledge_other"
    assert result.knowledge_query == "where is your company located"
    assert result.reason == "company question"
    assert result.store_overview_request is True
    assert result.llm_call_count == 1


@pytest.mark.asyncio
async def test_infer_chat_interpretation_uses_company_info_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(*args, **kwargs):
        assert kwargs.get("usage_kind") == "chat_understanding"
        return _understanding_payload(
            "company_info",
            reason="company question",
            confidence=0.95,
            needs_knowledge=True,
            knowledge_query="where is your company located",
            store_overview_request=True,
        )

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_chat_interpretation(
        user_text="Where is the company?",
        locale="en-US",
        channel="widget",
        alias_map={},
        parser_rules=_rules(),
        sku_tokens=[],
    )

    assert result.execution_decision.route_decision.workflow == "knowledge"
    assert result.execution_decision.route_decision.knowledge_query == "where is your company located"
    assert result.execution_decision.route_decision.store_overview_request is True
    assert result.execution_decision.selection_source == "llm"
    assert result.llm_call_count == 1
    assert result.debug["llm_chat_interpretation_internal_workflow"] == "company_info"


@pytest.mark.asyncio
async def test_infer_chat_interpretation_marks_product_detail_when_sku_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        if usage_kind == "chat_understanding":
            return _understanding_payload(
                "product_detail",
                reason="sku stock question",
                confidence=0.93,
                needs_products=True,
            )
        if usage_kind == "chat_detail_query_inference":
            return {
                "requested_fields": [],
                "attribute_filters": {},
                "wants_image": False,
                "semantic_hints": [],
                "clarify_focus": "",
                "confidence": 0.88,
            }
        raise AssertionError(f"unexpected usage_kind: {usage_kind}")

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_chat_interpretation(
        user_text="stock for ABC-1",
        locale="en-US",
        channel="widget",
        alias_map={},
        parser_rules=_rules(),
        sku_tokens=["ABC-1"],
    )

    assert result.execution_decision.route_decision.workflow == "catalog"
    assert result.execution_decision.route_decision.needs_products is True
    assert result.detail.requested_fields == ["attributes"]
    assert result.llm_call_count == 2
    assert result.debug["llm_chat_interpretation_internal_workflow"] == "product_detail"


@pytest.mark.asyncio
async def test_classify_chat_surface_intent_uses_entity_hints_over_legacy_workflow_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_understanding(**kwargs):
        return SimpleNamespace(
            workflow_hypothesis="catalog_search",
            intent_confidence=0.9,
            reason="policy_signal_detected",
            knowledge_query="what is your return policy",
            store_overview_request=False,
            llm_call_count=0,
            entity_hints={
                "knowledge_tags": ["refunds"],
                "has_policy_signal": True,
                "has_knowledge_signal": True,
                "preferred_knowledge_query": "what is your return policy",
            },
            debug={},
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.llm_attribute_extractor.build_understanding_result",
        fake_understanding,
    )

    result = await classify_chat_surface_intent(
        user_text="what is your return policy",
        locale="en-US",
        channel="widget",
    )

    assert result.intent_family == "knowledge_other"
    assert result.knowledge_query == "what is your return policy"
