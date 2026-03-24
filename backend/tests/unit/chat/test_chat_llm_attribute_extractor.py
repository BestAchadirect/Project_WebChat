from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.llm_service import llm_service
from app.services.chat.parsing.llm_attribute_extractor import enrich_product_attribute_filters
from app.services.chat.parsing.parser_rule_types import build_rule_set


def _rules():
    return build_rule_set(
        requested_field_patterns={},
        value_extract_patterns={},
        detection_attribute_order=["finish", "category"],
        allowed_attribute_filters=["finish", "category", "material", "gauge", "threading"],
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
                "finish": "sterilized",
            },
            "semantic_hints": ["sterilization"],
            "clarify_focus": "sterilization_meaning",
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
    assert result.semantic_hints == ["sterilization"]
    assert result.clarify_focus == "sterilization_meaning"
    assert result.confidence == pytest.approx(0.91)
    assert result.llm_call_count == 1
    assert result.debug["llm_attribute_interpretation_used"] is True
    assert result.debug["llm_exact_filter_keys"] == ["gauge"]
    assert result.debug["semantic_hint_keys"] == ["sterilization"]
    assert result.debug["semantic_hint_clarify_focus"] == "sterilization_meaning"


@pytest.mark.asyncio
async def test_enrich_product_attribute_filters_uses_heuristic_semantic_hint_when_llm_fails(
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
    assert result.semantic_hints == ["sterilization"]
    assert result.clarify_focus == "sterilization_meaning"
    assert result.llm_call_count == 0
    assert result.debug["semantic_hint_source"] == "heuristic"
