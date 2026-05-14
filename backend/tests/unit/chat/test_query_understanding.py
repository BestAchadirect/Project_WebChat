from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.ai.llm_service import llm_service
from app.services.chat.parsing.query_understanding import (
    QueryHardConstraints,
    compute_searchable_enough,
    infer_catalog_query_understanding,
)


def test_searchable_enough_accepts_broad_but_product_scoped_queries() -> None:
    assert compute_searchable_enough(
        text="show me cute nose rings",
        product_type_terms=["nose ring"],
        soft_hints=["cute"],
    )
    assert compute_searchable_enough(
        text="something gothic for septum",
        product_type_terms=["septum"],
        soft_hints=["gothic"],
    )
    assert compute_searchable_enough(
        text="do you have 16g?",
        hard_constraints=QueryHardConstraints(gauge=["16g"]),
    )
    assert compute_searchable_enough(
        text="show more like this",
        previous_product_ids=["p1"],
    )


def test_searchable_enough_rejects_unanchored_detail_or_style_only_queries() -> None:
    assert not compute_searchable_enough(text="how much is this?")
    assert not compute_searchable_enough(text="is it available?")
    assert not compute_searchable_enough(text="show me something nice", soft_hints=["nice"])
    assert not compute_searchable_enough(text="what about this one?")


@pytest.mark.asyncio
async def test_query_understanding_invalid_json_schema_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_QUERY_UNDERSTANDING_V2_ENABLED", True)

    async def fake_generate_chat_json(**kwargs):
        return {
            "intent": "catalog_search",
            "is_searchable_enough": True,
            "unexpected": "field",
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_catalog_query_understanding(
        user_text="show titanium labrets",
        normalized_text="show titanium labrets",
    )

    assert result.valid is False
    assert result.trusted is False
    assert result.debug["llm_query_understanding_valid"] is False
    assert result.debug["llm_query_understanding_error"]


@pytest.mark.asyncio
async def test_query_understanding_rule_can_override_false_searchable_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_QUERY_UNDERSTANDING_V2_ENABLED", True)

    async def fake_generate_chat_json(**kwargs):
        return {
            "intent": "catalog_search",
            "is_searchable_enough": False,
            "clarification_needed": True,
            "clarification_reason": "too broad",
            "missing_slots": ["product_type"],
            "product_anchor_required": False,
            "uses_previous_context": False,
            "resolved_context_reference": None,
            "product_type_terms": ["nose ring"],
            "category_terms": [],
            "hard_constraints": {
                "material": [],
                "gauge": [],
                "diameter": [],
                "length": [],
                "color": [],
                "threading": [],
                "jewelry_type": [],
                "category": [],
                "price": None,
                "stock": None,
                "sku": [],
            },
            "soft_hints": ["cute"],
            "semantic_query": "cute nose rings",
            "strictness": {"style": "preferred"},
            "confidence": {"intent": 0.92, "constraints": 0.7, "searchable": 0.3},
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await infer_catalog_query_understanding(
        user_text="show me cute nose rings",
        normalized_text="show me cute nose rings",
    )

    assert result.valid is True
    assert result.trusted is True
    assert result.understanding is not None
    assert result.understanding.is_searchable_enough is True
    assert result.understanding.clarification_needed is False
