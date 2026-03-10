from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatComponent, ChatRequest, KnowledgeSource, ProductCard
from app.services.ai.llm_service import llm_service
from app.services.chat import product_presentation
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.types import ComponentSource, ComponentType


def _canonical_product(*, sku: str, title: str, master_code: str) -> CanonicalProduct:
    return CanonicalProduct(
        product_id=uuid4(),
        sku=sku,
        title=title,
        price=Decimal("10.00"),
        currency="USD",
        in_stock=True,
        stock_qty=5,
        material="Gold",
        gauge="16g",
        image_url="https://example.com/image.jpg",
        description="Sample product",
        attributes={"master_code": master_code, "material": "Gold", "color": "Gold"},
        product_url="https://example.com/product",
    )


def test_dedupe_products_by_master_code_counts_unique_masters() -> None:
    products = [
        _canonical_product(sku="A-1", title="Alpha", master_code="ALPHA"),
        _canonical_product(sku="A-2", title="Alpha", master_code="ALPHA"),
        _canonical_product(sku="B-1", title="Beta", master_code="BETA"),
    ]

    deduped, total_unique = product_presentation.dedupe_products_by_master_code(products)

    assert len(deduped) == 2
    assert total_unique == 2


def test_product_presentation_builds_filter_based_copy() -> None:
    reply = product_presentation.build_product_match_reply(
        attribute_filters={"color": "gold", "material": "gold"}
    )
    follow_up = product_presentation.build_see_more_follow_up(
        attribute_filters={"color": "gold", "material": "gold"},
        user_text="I am looking for Gold product",
    )

    assert reply == "I found products that match what you're looking for in Gold color with Gold material."
    assert follow_up == "See more in Gold color"


def test_product_presentation_builds_extended_filter_copy() -> None:
    reply = product_presentation.build_product_match_reply(
        attribute_filters={"category": "sterilized", "design": "heart", "jewelry_type": "ring"}
    )
    follow_up = product_presentation.build_see_more_follow_up(
        attribute_filters={"category": "sterilized", "design": "heart", "jewelry_type": "ring"},
        user_text="show sterilized heart rings",
    )

    assert reply == "I found products that match what you're looking for in Sterilized for Ring with Heart design."
    assert follow_up == "See more Sterilized Ring"


def test_component_pipeline_derive_legacy_uses_attribute_copy_and_see_more() -> None:
    context = ComponentContext(
        user_text="I am looking for Gold product",
        locale="en-US",
        intent="browse_products",
        query_summary="I am looking for Gold product",
        source=ComponentSource.SQL,
        selected_components=[ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS],
        canonical_products=[
            _canonical_product(sku="A-1", title="Alpha", master_code="ALPHA"),
            _canonical_product(sku="B-1", title="Beta", master_code="BETA"),
        ],
        result_count=12,
        attribute_filters={"color": "gold", "material": "gold"},
    )
    components = [ChatComponent(type="product_cards", data={"cards": [{}]})]

    payload = ComponentPipeline._derive_legacy(context=context, components=components)

    assert payload["reply_text"] == "I found products that match what you're looking for in Gold color with Gold material."
    assert payload["follow_up_questions"] == ["See more in Gold color"]
    assert len(payload["product_carousel"]) == 2


@pytest.mark.asyncio
async def test_component_pipeline_uses_complementary_mapping_for_recommendation_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = CanonicalProduct(
        product_id=uuid4(),
        sku="LAB-1",
        title="Threadless Labret Post",
        price=Decimal("8.00"),
        currency="USD",
        in_stock=True,
        stock_qty=10,
        material="Titanium",
        gauge="16g",
        image_url=None,
        description="Anchor product",
        attributes={"master_code": "LAB-1", "jewelry_type": "Labret", "threading": "threadless", "gauge": "16g"},
        product_url="https://example.com/labret",
    )
    top = CanonicalProduct(
        product_id=uuid4(),
        sku="TOP-1",
        title="Threadless Heart Top",
        price=Decimal("5.00"),
        currency="USD",
        in_stock=True,
        stock_qty=20,
        material="Titanium",
        gauge="16g",
        image_url=None,
        description="Compatible top",
        attributes={"master_code": "TOP-1", "jewelry_type": "Top", "threading": "threadless", "gauge": "16g"},
        product_url="https://example.com/top",
    )

    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    class _KnowledgeStub:
        async def search(self, *args, **kwargs):
            return []

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[anchor.product_id]), {"structured_read_mode": "eav", "projection_hit": False}

        async def structured_count(self, **kwargs):
            return 1

        async def vector_search(self, **kwargs):
            card = ProductCard(
                id=top.product_id,
                object_id=top.sku,
                sku=top.sku,
                legacy_sku=[],
                name=top.title,
                description=top.description,
                price=float(top.price),
                currency=top.currency,
                stock_status="in_stock",
                image_url=top.image_url,
                product_url=top.product_url,
                attributes=dict(top.attributes),
            )
            return SimpleNamespace(cards=[card], distance_by_id={str(top.product_id): 0.08})

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        items = []
        for raw in product_ids:
            if str(raw) == str(anchor.product_id):
                items.append(anchor)
            if str(raw) == str(top.product_id):
                items.append(top)
        return items, {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="What goes with this labret?", locale="en-US"),
        conversation_id=42,
        run_id="run-1",
    )

    assert result.response.intent == "recommend_products"
    assert result.debug.get("recommendation_mode_requested") == "complementary_items"
    assert result.debug.get("recommendation_expand_source") == "complementary_mapping"
    assert result.debug.get("recommendation_complementary_label") == "Labret tops"
    assert any(component.type.value == "recommendations" for component in result.response.components)


@pytest.mark.asyncio
async def test_component_pipeline_store_overview_request_returns_featured_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labret = CanonicalProduct(
        product_id=uuid4(),
        sku="LAB-1",
        title="Titanium Labret",
        price=Decimal("8.00"),
        currency="USD",
        in_stock=True,
        stock_qty=10,
        material="Titanium",
        gauge="16g",
        image_url=None,
        description="Featured labret",
        attributes={"master_code": "LAB-1", "jewelry_type": "Labret", "material": "Titanium"},
        product_url="https://example.com/labret",
    )
    ring = CanonicalProduct(
        product_id=uuid4(),
        sku="RING-1",
        title="Gold Ring",
        price=Decimal("12.00"),
        currency="USD",
        in_stock=True,
        stock_qty=6,
        material="Gold",
        gauge="18g",
        image_url=None,
        description="Featured ring",
        attributes={"master_code": "RING-1", "jewelry_type": "Ring", "material": "Gold"},
        product_url="https://example.com/ring",
    )

    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=_RedisStub(),
    )

    async def fake_featured_ids(*, limit):
        return [str(labret.product_id), str(ring.product_id)]

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [labret, ring], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(pipeline, "_load_featured_product_ids", fake_featured_ids)
    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="What do you have in your store?", locale="en-US"),
        conversation_id=42,
        run_id="run-store-overview",
    )

    assert result.response.intent == "browse_products"
    assert result.debug.get("store_overview_request") is True
    assert "We carry products like" in result.response.reply_text
    assert len(result.response.product_carousel) == 2
    assert any(item.startswith("Show ") for item in result.response.follow_up_questions)


@pytest.mark.asyncio
async def test_component_pipeline_knowledge_answer_falls_back_when_llm_reply_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=_RedisStub(),
    )

    async def fake_generate_chat_json(*args, **kwargs):
        return {"reply": ""}

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    answer, from_cache = await pipeline._knowledge_answer_once(
        question="What is your return policy?",
        sources=[
            KnowledgeSource(
                source_id="src-1",
                chunk_id="chunk-1",
                title="Returns Policy",
                content_snippet="You can return eligible items within 30 days with approval from the support team.",
                category="Policy",
                relevance=0.9,
                url="https://example.com/returns",
                distance=0.1,
            )
        ],
        locale="en-US",
        llm_cache_key="test-key",
    )

    assert from_cache is False
    assert answer.startswith("Here is what I found:")
    assert "Returns Policy" in answer
