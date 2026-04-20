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
)
from app.services.chat.parsing.parser_rule_types import build_rule_set


def _rules():
    return build_rule_set(
        requested_field_patterns={},
        value_extract_patterns={},
        detection_attribute_order=["finish", "category"],
        allowed_attribute_filters=["finish", "category", "material", "gauge", "threading", "jewelry_type"],
    )


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
async def test_classify_chat_surface_intent_prefers_support_contact() -> None:
    result = await classify_chat_surface_intent(
        user_text="I want to talk to a sale person",
        locale="en-US",
        channel="widget",
    )

    assert result.intent_family == "support_contact"
    assert result.knowledge_query == "how can I contact customer service"
    assert result.reason == "company_signal_detected"
    assert result.confidence == pytest.approx(0.95)
    assert result.llm_call_count == 0


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
        user_text="Can you write Python code for me?",
        locale="en-US",
        channel="widget",
    )

    assert calls["count"] == 1
    assert result.intent_family == "off_topic"
    assert result.reason == "unrelated request"
    assert result.confidence == pytest.approx(0.84)
    assert result.llm_call_count == 1


@pytest.mark.asyncio
async def test_classify_chat_surface_intent_detects_company_question_without_vector_probe() -> None:
    result = await classify_chat_surface_intent(
        user_text="Where is the company?",
        locale="en-US",
        channel="widget",
    )

    assert result.intent_family == "knowledge_other"
    assert result.knowledge_query == "where is your company located"
    assert result.reason == "company_signal_detected"
    assert result.store_overview_request is True
    assert result.llm_call_count == 0


@pytest.mark.asyncio
async def test_infer_chat_interpretation_uses_staged_company_info_route() -> None:
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
    assert result.execution_decision.selection_source == "deterministic"
    assert result.llm_call_count == 0
    assert result.debug["llm_chat_interpretation_internal_workflow"] == "company_info"


@pytest.mark.asyncio
async def test_infer_chat_interpretation_marks_product_detail_when_sku_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
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
    assert result.llm_call_count == 1
    assert result.debug["llm_chat_interpretation_internal_workflow"] == "product_detail"
