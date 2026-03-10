from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatRequest, ProductCard
from app.services.ai.llm_service import llm_service
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.detail_query_parser import DetailQuery
from app.services.chat.product_detail_resolver import ProductDetailResolver
from app.services.chat.result_policy import classify_match_tier, semantic_fallback_decision


class _RedisStub:
    async def get_json(self, key):
        return None

    async def set_json(self, key, value, ttl_seconds=0):
        return None


class _KnowledgeStub:
    async def search(self, *args, **kwargs):
        return []


def _product_card(*, sku: str, material: str) -> ProductCard:
    return ProductCard(
        id=uuid4(),
        object_id=sku,
        sku=sku,
        name=sku,
        price=1.0,
        currency="USD",
        stock_status="in_stock",
        attributes={"material": material},
    )


def _canonical_product(*, sku: str, title: str, attributes: dict | None = None) -> CanonicalProduct:
    attrs = attributes or {}
    return CanonicalProduct(
        product_id=uuid4(),
        sku=sku,
        title=title,
        price=Decimal("12.50"),
        currency="USD",
        in_stock=True,
        stock_qty=5,
        material=str(attrs.get("material") or "Steel"),
        gauge=str(attrs.get("gauge") or "14g"),
        image_url=None,
        description=title,
        attributes=attrs,
        product_url="https://example.com/product",
    )


def test_detail_filtering_is_deterministic_without_llm() -> None:
    steel = _product_card(sku="ST-1", material="Steel")
    titanium = _product_card(sku="TI-1", material="Titanium")
    resolution = ProductDetailResolver.resolve_detail_request(
        candidate_cards=[steel, titanium],
        distance_by_id={str(steel.id): 0.2, str(titanium.id): 0.1},
        requested_fields=["attributes"],
        attribute_filters={"material": "steel"},
        sku_token=None,
        nlu_product_code=None,
        max_matches=3,
        min_confidence=0.55,
    )
    assert [item.sku for item in resolution.matches] == ["ST-1"]


def test_semantic_fallback_decision_blocks_structured_filters() -> None:
    decision = semantic_fallback_decision(
        intent="browse_products",
        attribute_filters={"material": "titanium"},
        sku_tokens=[],
        detail_mode=False,
        compare_requested=False,
        store_overview_request=False,
    )
    assert decision.allow is False
    assert decision.reason == "structured_filters_present"
    assert classify_match_tier(structured_found=False, semantic_found=False) == "no_match"


def test_semantic_fallback_decision_allows_discovery_queries() -> None:
    decision = semantic_fallback_decision(
        intent="browse_products",
        attribute_filters={},
        sku_tokens=[],
        detail_mode=False,
        compare_requested=False,
        store_overview_request=False,
    )
    assert decision.allow is True
    assert decision.reason == "discovery_query"
    assert classify_match_tier(structured_found=False, semantic_found=True) == "semantic_suggestion"


@pytest.mark.asyncio
async def test_component_pipeline_structured_no_match_returns_clarify_without_vector_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[]), {"structured_read_mode": "eav", "projection_hit": False}

        async def structured_count(self, **kwargs):
            return 0

        async def smart_search(self, **kwargs):
            raise AssertionError("semantic fallback should be blocked for exact structured filters")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    def fake_parse(*, user_text: str, nlu_data):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={"material": "titanium"},
            wants_image=False,
            is_detail_request=False,
        )

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="show titanium labrets", locale="en-US"),
        conversation_id=77,
        run_id="run-no-match",
    )

    assert result.response.intent == "browse_products"
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert "couldn't find products matching those exact details" in result.response.reply_text.lower()
    assert result.debug.get("semantic_fallback_allowed") is False
    assert result.debug.get("semantic_fallback_reason") == "structured_filters_present"
    assert result.debug.get("match_tier") == "no_match"


@pytest.mark.asyncio
async def test_component_pipeline_discovery_query_returns_semantic_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _canonical_product(
        sku="LAB-1",
        title="Steel Labret",
        attributes={"master_code": "LAB-1", "material": "steel", "jewelry_type": "labret"},
    )

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[]), {"structured_read_mode": "eav", "projection_hit": False}

        async def structured_count(self, **kwargs):
            return 0

        async def smart_search(self, **kwargs):
            return SimpleNamespace(
                product_ids=[str(product.product_id)],
                cards=[],
                distance_by_id={str(product.product_id): 0.08},
            )

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    def fake_parse(*, user_text: str, nlu_data):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            is_detail_request=False,
        )

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse",
        fake_parse,
    )
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="show me something nice", locale="en-US"),
        conversation_id=77,
        run_id="run-semantic",
    )

    assert result.response.intent == "browse_products"
    assert len(result.response.product_carousel) == 1
    assert result.debug.get("component_source") == "vector"
    assert result.debug.get("match_tier") == "semantic_suggestion"


@pytest.mark.asyncio
async def test_component_pipeline_product_browse_reply_is_deterministic_without_llm_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _canonical_product(
        sku="LAB-14-STEEL-1",
        title="Labret 14g Steel",
        attributes={"master_code": "LAB-14-STEEL-1", "jewelry_type": "labret", "gauge": "14g", "material": "steel"},
    )

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[str(product.product_id)]), {"structured_read_mode": "eav", "projection_hit": False}

        async def structured_count(self, **kwargs):
            return 1

        async def smart_search(self, **kwargs):
            raise AssertionError("embedding should be skipped when structured SQL has results")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    def fake_parse(*, user_text: str, nlu_data):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={"jewelry_type": "labret", "gauge": "14g", "material": "steel"},
            wants_image=False,
            is_detail_request=False,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Give me a Labret with 14g with steel", locale="en-US"),
        conversation_id=77,
        run_id="run-deterministic-browse",
    )

    assert result.response.intent == "browse_products"
    assert result.llm_calls == 0
    assert result.debug.get("component_source") == "sql"
    assert result.debug.get("match_tier") == "exact_match"
    assert "steel material" in result.response.reply_text.lower()
