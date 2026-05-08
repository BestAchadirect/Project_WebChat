from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.ai.llm_service import llm_service
from app.services.chat.parsing import llm_attribute_extractor as extractor_module
from app.services.chat.parsing.llm_attribute_extractor import (
    classify_chat_surface_intent,
    enrich_product_attribute_filters,
    infer_attribute_list_target,
    infer_chat_interpretation,
    infer_detail_query,
)
from app.services.chat.parsing.detail_query_parser import DetailQueryParser
from app.services.chat.parsing.parser_rule_types import build_rule_set


def _rules():
    return build_rule_set(
        requested_field_patterns={},
        value_extract_patterns={},
        detection_attribute_order=["finish", "category"],
        allowed_attribute_filters=["finish", "category", "material", "gauge", "threading", "jewelry_type"],
    )


CATALOG_ATTRIBUTE_CASES = [
    {
        "attribute": "category",
        "message": "Show Belly Bananas for belly piercing",
        "llm_value": ["Belly Bananas", "Belly Piercing"],
        "expected": "belly bananas;;belly piercing",
        "is_multivalue": True,
    },
    {
        "attribute": "material",
        "message": "Show Titanium G23 jewelry",
        "llm_value": "Titanium G23",
        "expected": "titanium g23",
    },
    {
        "attribute": "jewelry_type",
        "message": "Find circular barbells",
        "llm_value": "Circular Barbells",
        "expected": "circular barbells",
    },
    {
        "attribute": "gauge",
        "message": "Find 14g body jewelry",
        "llm_value": "14g",
        "expected": "14g",
    },
    {
        "attribute": "length",
        "message": "Show barbells with 10mm length",
        "llm_value": "10mm",
        "expected": "10mm",
    },
    {
        "attribute": "color",
        "message": "Show black PVD jewelry",
        "llm_value": "Black PVD",
        "expected": "black pvd",
    },
    {
        "attribute": "size_in_pack",
        "message": "Show packs with 20 pieces sizes 2g to 00g",
        "llm_value": "20 Pieces - Sizes 2g - 00g",
        "expected": "20 pieces - sizes 2g - 00g",
    },
    {
        "attribute": "crystal_color",
        "message": "Show clear crystal products",
        "llm_value": "Clear",
        "expected": "clear",
    },
    {
        "attribute": "quantity_in_bulk",
        "message": "Show bulk packs with 100 pcs",
        "llm_value": "100 pcs",
        "expected": "100 pcs",
    },
    {
        "attribute": "cz_color",
        "message": "Show AB CZ color jewelry",
        "llm_value": "AB",
        "expected": "ab",
    },
    {
        "attribute": "size",
        "message": "Show medium size jewelry",
        "llm_value": "Medium",
        "expected": "medium",
    },
    {
        "attribute": "outer_diameter",
        "message": "Show rings with 8 mm outer diameter",
        "llm_value": "8 mm",
        "expected": "8 mm",
    },
    {
        "attribute": "packing_option",
        "message": "Show individually packed products",
        "llm_value": "Individually Packed",
        "expected": "individually packed",
    },
    {
        "attribute": "pincher_size",
        "message": "Show small pincher size products",
        "llm_value": "Small",
        "expected": "small",
    },
    {
        "attribute": "height",
        "message": "Show 12mm height products",
        "llm_value": "12mm",
        "expected": "12mm",
    },
    {
        "attribute": "design",
        "message": "Show heart design jewelry",
        "llm_value": "Heart",
        "expected": "heart",
    },
    {
        "attribute": "threading",
        "message": "Show internally threaded jewelry",
        "llm_value": "Internally Threaded",
        "expected": "internally threaded",
    },
]


def _catalog_attribute_metadata() -> list[dict[str, Any]]:
    return [
        {
            "name": str(case["attribute"]),
            "display_name": str(case["attribute"]).replace("_", " ").title(),
            "data_type": "string",
            "is_multivalue": bool(case.get("is_multivalue", False)),
        }
        for case in CATALOG_ATTRIBUTE_CASES
    ]


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
@pytest.mark.parametrize(
    "case",
    CATALOG_ATTRIBUTE_CASES,
    ids=[str(case["attribute"]) for case in CATALOG_ATTRIBUTE_CASES],
)
async def test_infer_detail_query_accepts_each_searchable_catalog_attribute(
    monkeypatch: pytest.MonkeyPatch,
    case: dict[str, Any],
) -> None:
    seen_payload: dict[str, Any] = {}

    async def fake_load_candidates(**kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        seen_payload.update(json.loads(messages[-1]["content"]))
        return {
            "requested_fields": [],
            "attribute_filters": {str(case["attribute"]): case["llm_value"]},
            "semantic_hints": [],
            "clarify_focus": "",
            "wants_image": False,
            "confidence": 0.94,
        }

    monkeypatch.setattr(extractor_module, "_load_attribute_value_candidates", fake_load_candidates)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_detail_query(
        user_text=str(case["message"]),
        workflow="catalog",
        alias_map={},
        parser_rules=_rules(),
        existing_filters={},
        db=SimpleNamespace(execute=object()),
        searchable_attribute_metadata=_catalog_attribute_metadata(),
    )

    attribute = str(case["attribute"])
    assert result.attribute_filters == {attribute: str(case["expected"])}
    assert attribute in seen_payload["searchable_attributes"]
    assert attribute in (
        list(seen_payload["allowed_exact_attributes"])
        + list(seen_payload["allowed_soft_attributes"])
    )
    assert seen_payload["attribute_metadata"] == _catalog_attribute_metadata()


def test_catalog_attribute_cases_cover_current_searchable_db_attributes() -> None:
    # Snapshot from eav_service.get_searchable_attribute_metadata against the current catalog.
    current_searchable = {
        "category",
        "material",
        "jewelry_type",
        "gauge",
        "length",
        "color",
        "size_in_pack",
        "crystal_color",
        "quantity_in_bulk",
        "cz_color",
        "size",
        "outer_diameter",
        "packing_option",
        "pincher_size",
        "height",
        "design",
        "threading",
    }
    assert {str(case["attribute"]) for case in CATALOG_ATTRIBUTE_CASES} == current_searchable


def test_attribute_value_candidates_ignore_question_noise_and_match_word_forms() -> None:
    tokens = extractor_module._query_value_candidate_tokens("Do you have any sterilization product?")

    assert tokens == ["sterilization"]
    assert extractor_module._matched_attribute_lookup_terms(
        value_norm="sterilized",
        tokens=tokens,
    ) == ["steril"]


def test_candidate_alignment_normalizes_customer_wording_to_db_value() -> None:
    aligned = extractor_module._align_candidate_filter_values(
        filters={"category": "sterilization"},
        attribute_value_candidates=[
            {
                "attribute": "category",
                "value": "Sterilized",
                "value_norm": "sterilized",
                "score": 6.7,
                "product_count": 7753,
            }
        ],
    )

    assert aligned == {"category": "sterilized"}


def test_approximate_candidate_scoring_handles_customer_typos() -> None:
    score, matched_terms = extractor_module._score_approximate_attribute_value_candidate(
        value_norm="sterilized",
        tokens=["strelized"],
        count=7753,
    )

    assert score >= 7.0
    assert matched_terms == ["strelized"]


def test_candidate_scoring_surfaces_simple_plural_normalized_values() -> None:
    tokens = extractor_module._query_value_candidate_tokens(
        "Show gold rings and tell me your return policy"
    )

    assert "policy" not in tokens
    assert "ring" in extractor_module._query_value_candidate_lookup_terms(tokens)
    simple_score = extractor_module._score_attribute_value_candidate(
        value_norm="ring",
        tokens=tokens,
        count=1193,
    )
    long_score = extractor_module._score_attribute_value_candidate(
        value_norm="new 18k yellow & white gold hinged segment rings",
        tokens=tokens,
        count=19,
    )
    assert simple_score > long_score


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
async def test_infer_detail_query_uses_only_searchable_attribute_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_payload: dict[str, Any] = {}

    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        seen_payload.update(json.loads(messages[-1]["content"]))
        return {
            "requested_fields": ["price", "stock"],
            "attribute_filters": {
                "body_part": "nose",
                "opal_color": "blue",
                "material": "titanium",
            },
            "semantic_hints": ["opal color"],
            "clarify_focus": "",
            "wants_image": False,
            "confidence": 0.91,
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_detail_query(
        user_text="Show titanium nose jewelry with blue opal color",
        workflow="catalog",
        alias_map={},
        parser_rules=_rules(),
        existing_filters={},
        searchable_attribute_names=["material"],
    )

    assert seen_payload["searchable_attributes"] == ["material"]
    assert result.requested_fields == ["price", "stock"]
    assert result.attribute_filters == {"material": "titanium"}
    assert result.semantic_hints == ["opal color"]
    assert result.debug["catalog_allowed_soft_attributes"] == ["material"]


@pytest.mark.asyncio
async def test_enrich_product_attribute_filters_passes_multivalue_metadata_and_keeps_category_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_payload: dict[str, Any] = {}

    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        seen_payload.update(json.loads(messages[-1]["content"]))
        return {
            "exact_filters": {},
            "soft_filters": {"category": ["Belly Bananas", "Checkers"]},
            "semantic_hints": [],
            "clarify_focus": "",
            "confidence": 0.93,
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await enrich_product_attribute_filters(
        db=object(),
        user_text="Show belly banana checkers",
        workflow="catalog",
        existing_filters={},
        alias_map={},
        parser_rules=_rules(),
        searchable_attribute_metadata=[
            {
                "name": "category",
                "display_name": "Category",
                "data_type": "string",
                "is_multivalue": True,
            }
        ],
    )

    assert seen_payload["searchable_attributes"] == ["category"]
    assert seen_payload["attribute_metadata"] == [
        {
            "name": "category",
            "display_name": "Category",
            "data_type": "string",
            "is_multivalue": True,
        }
    ]
    assert result.soft_filters == {"category": "belly bananas;;checkers"}
    assert result.debug["catalog_searchable_attribute_metadata"][0]["is_multivalue"] is True


@pytest.mark.asyncio
async def test_infer_detail_query_canonicalizes_legacy_body_part_when_searchable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = build_rule_set(
        requested_field_patterns={},
        value_extract_patterns={},
        detection_attribute_order=[],
        allowed_attribute_filters=["body_location"],
    )

    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        return {
            "requested_fields": [],
            "attribute_filters": {"body_part": "nose"},
            "semantic_hints": [],
            "clarify_focus": "",
            "wants_image": False,
            "confidence": 0.92,
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_detail_query(
        user_text="Show nose jewelry",
        workflow="catalog",
        alias_map={},
        parser_rules=rules,
        existing_filters={},
        searchable_attribute_names=["body_location"],
    )

    assert result.attribute_filters == {"body_location": "nose"}
    assert result.debug["catalog_allowed_exact_attributes"] == ["body_location"]


@pytest.mark.asyncio
async def test_infer_detail_query_passes_db_value_candidates_to_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_payload: dict[str, Any] = {}

    async def fake_load_candidates(**kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["user_text"] == "find me belly banana"
        return [
            {
                "attribute": "category",
                "value": "Belly Bananas",
                "value_norm": "belly bananas",
                "matched_terms": ["belly", "banana"],
                "product_count": 31031,
                "score": 17.0,
            }
        ]

    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        seen_payload.update(json.loads(messages[-1]["content"]))
        return {
            "requested_fields": [],
            "attribute_filters": {"category": "Belly Bananas"},
            "semantic_hints": [],
            "clarify_focus": "",
            "wants_image": False,
            "confidence": 0.94,
        }

    monkeypatch.setattr(extractor_module, "_load_attribute_value_candidates", fake_load_candidates)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_detail_query(
        user_text="find me belly banana",
        workflow="catalog",
        alias_map={},
        parser_rules=_rules(),
        existing_filters={},
        db=SimpleNamespace(execute=object()),
        searchable_attribute_names=["category", "design"],
    )

    assert seen_payload["attribute_value_candidates"] == [
        {
            "attribute": "category",
            "value": "Belly Bananas",
            "value_norm": "belly bananas",
            "matched_terms": ["belly", "banana"],
            "product_count": 31031,
            "score": 17.0,
        }
    ]
    assert result.requested_fields == []
    assert result.wants_image is False
    assert result.attribute_filters == {"category": "belly bananas"}
    assert result.debug["catalog_attribute_value_candidate_count"] == 1


@pytest.mark.asyncio
async def test_infer_detail_query_passes_low_cardinality_db_options_to_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_payload: dict[str, Any] = {}

    async def fake_load_candidates(**kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fake_load_options(**kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "attribute": "packing_option",
                "value_count": 2,
                "values": [
                    {
                        "value": "Blister Package",
                        "value_norm": "blister package",
                        "product_count": 71,
                    },
                    {
                        "value": "Extra-Thin Package to Save Shipping Cost",
                        "value_norm": "extra-thin package to save shipping cost",
                        "product_count": 58,
                    },
                ],
            }
        ]

    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        seen_payload.update(json.loads(messages[-1]["content"]))
        return {
            "requested_fields": [],
            "attribute_filters": {},
            "semantic_hints": ["individually packed"],
            "clarify_focus": "",
            "wants_image": False,
            "confidence": 0.84,
        }

    monkeypatch.setattr(extractor_module, "_load_attribute_value_candidates", fake_load_candidates)
    monkeypatch.setattr(extractor_module, "_load_attribute_value_options", fake_load_options)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_detail_query(
        user_text="Show individually packed products",
        workflow="catalog",
        alias_map={},
        parser_rules=_rules(),
        existing_filters={},
        db=SimpleNamespace(execute=object()),
        searchable_attribute_names=["packing_option"],
    )

    assert seen_payload["attribute_value_options"] == [
        {
            "attribute": "packing_option",
            "value_count": 2,
            "values": [
                {
                    "value": "Blister Package",
                    "value_norm": "blister package",
                    "product_count": 71,
                },
                {
                    "value": "Extra-Thin Package to Save Shipping Cost",
                    "value_norm": "extra-thin package to save shipping cost",
                    "product_count": 58,
                },
            ],
        }
    ]
    assert result.attribute_filters == {}
    assert result.semantic_hints == ["individually packed"]
    assert result.debug["catalog_attribute_value_options"][0]["attribute"] == "packing_option"


@pytest.mark.asyncio
async def test_infer_detail_query_collapses_duplicate_candidate_category_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load_candidates(**kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "attribute": "category",
                "value": "Belly Bananas",
                "value_norm": "belly bananas",
                "matched_terms": ["belly", "banana"],
                "product_count": 31031,
                "score": 17.0,
            },
            {
                "attribute": "category",
                "value": "Belly Banana",
                "value_norm": "belly banana",
                "matched_terms": ["belly", "banana"],
                "product_count": 54,
                "score": 14.0,
            },
        ]

    async def fake_generate_chat_json(*, messages, model, temperature, max_tokens, usage_kind, **extra):
        return {
            "requested_fields": [],
            "attribute_filters": {"category": ["Belly Banana", "Belly Bananas"]},
            "semantic_hints": [],
            "clarify_focus": "",
            "wants_image": False,
            "confidence": 0.94,
        }

    monkeypatch.setattr(extractor_module, "_load_attribute_value_candidates", fake_load_candidates)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_detail_query(
        user_text="find me belly banana",
        workflow="catalog",
        alias_map={},
        parser_rules=_rules(),
        existing_filters={},
        db=SimpleNamespace(execute=object()),
        searchable_attribute_names=["category"],
    )

    assert result.attribute_filters == {"category": "belly bananas"}


@pytest.mark.asyncio
async def test_infer_detail_query_uses_strong_db_candidate_when_llm_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load_candidates(**kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "attribute": "category",
                "value": "Belly Bananas",
                "value_norm": "belly bananas",
                "matched_terms": ["belly", "banana"],
                "product_count": 31031,
                "score": 17.0,
            }
        ]

    async def failing_generate_chat_json(*args, **kwargs):
        raise TimeoutError("Request timed out.")

    monkeypatch.setattr(extractor_module, "_load_attribute_value_candidates", fake_load_candidates)
    monkeypatch.setattr(llm_service, "generate_chat_json", failing_generate_chat_json)

    result = await infer_detail_query(
        user_text="find me belly banana",
        workflow="catalog",
        alias_map={},
        parser_rules=_rules(),
        existing_filters={},
        db=SimpleNamespace(execute=object()),
        searchable_attribute_names=["category"],
    )

    assert result.attribute_filters == {"category": "belly bananas"}
    detail = DetailQueryParser.build_from_inference(
        inference=result,
        parser_rules=_rules(),
        searchable_attribute_names=["category"],
    )
    assert detail.attribute_filters == {"category": "belly bananas"}
    assert result.requested_fields == []
    assert result.wants_image is False
    assert result.semantic_hints == []
    assert result.debug["llm_detail_query_error"] == "Request timed out."
    assert result.debug["llm_detail_query_fallback_source"] == "attribute_value_candidate"


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
