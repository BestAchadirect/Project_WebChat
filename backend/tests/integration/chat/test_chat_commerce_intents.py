from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatRequest
from app.services.chat import routing_policy
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.types import ComponentSource


class _RedisStub:
    async def get_json(self, key):
        return None

    async def set_json(self, key, value, ttl_seconds=0):
        return None


class _KnowledgeStub:
    async def search(self, *args, **kwargs):
        return []


def _canonical_product(*, sku: str, title: str, material: str) -> CanonicalProduct:
    return CanonicalProduct(
        product_id=uuid4(),
        sku=sku,
        title=title,
        price=Decimal("10.00"),
        currency="USD",
        in_stock=True,
        stock_qty=5,
        material=material,
        gauge="16g",
        image_url=None,
        description=title,
        attributes={"master_code": sku, "material": material, "jewelry_type": "labret"},
        product_url=f"https://example.com/{sku.lower()}",
    )


def _workflow_decision(
    workflow: str,
    *,
    store_overview_request: bool = False,
) -> routing_policy.WorkflowDecision:
    return routing_policy.WorkflowDecision(
        workflow=workflow,
        source=ComponentSource.SQL,
        needs_products=workflow in {"catalog", "comparison", "recommendation"},
        needs_knowledge=workflow == "knowledge",
        needs_clarification=workflow == "fallback",
        store_overview_request=store_overview_request,
        reason="test_override",
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_component_pipeline_compare_workflow_returns_compare_component() -> None:
    first = _canonical_product(sku="AAA-1", title="Titanium Labret AAA-1", material="titanium")
    second = _canonical_product(sku="BBB-2", title="Steel Labret BBB-2", material="steel")

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            sku_token = str(kwargs.get("sku_token") or "").lower()
            if sku_token == "aaa-1":
                return SimpleNamespace(product_ids=[str(first.product_id)]), {"structured_read_mode": "eav"}
            if sku_token == "bbb-2":
                return SimpleNamespace(product_ids=[str(second.product_id)]), {"structured_read_mode": "eav"}
            return SimpleNamespace(product_ids=[]), {"structured_read_mode": "eav"}

        async def structured_count(self, **kwargs):
            return 0

        async def smart_search(self, **kwargs):
            raise AssertionError("compare flow should not use semantic fallback")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        ordered = []
        for product_id in product_ids:
            if str(product_id) == str(first.product_id):
                ordered.append(first)
            elif str(product_id) == str(second.product_id):
                ordered.append(second)
        return ordered, {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="compare AAA-1 and BBB-2", locale="en-US"),
        conversation_id=88,
        run_id="run-compare",
        route_decision_override=_workflow_decision("comparison"),
    )

    assert result.response.routing.workflow == "comparison"
    assert len(result.response.product_carousel) == 2
    assert any(component.type.value == "compare" for component in result.response.components)
    assert "compare" in result.response.reply_text.lower()
    assert result.debug.get("compare_mode") == "sku_first"


@pytest.mark.asyncio
async def test_component_pipeline_compare_requires_two_products() -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="compare AAA-1", locale="en-US"),
        conversation_id=88,
        run_id="run-compare-missing",
        route_decision_override=_workflow_decision("comparison"),
    )

    assert result.response.routing.workflow == "comparison"
    assert result.response.product_carousel == []
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert "two sku" in result.response.reply_text.lower()


@pytest.mark.asyncio
async def test_component_pipeline_recommend_workflow_returns_recommendation_route() -> None:
    first = _canonical_product(sku="LAB-1", title="Titanium Labret 1", material="titanium")
    second = _canonical_product(sku="LAB-2", title="Titanium Labret 2", material="titanium")

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[str(first.product_id), str(second.product_id)]), {
                "structured_read_mode": "eav",
                "projection_hit": False,
            }

        async def structured_count(self, **kwargs):
            return 2

        async def smart_search(self, **kwargs):
            raise AssertionError("semantic fallback should not run when structured recommendation seeds exist")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [first, second], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_expand(*, anchor_product_ids, query_embedding, limit):
        return SimpleNamespace(
            product_ids=[],
            source="structured_only",
            used_anchor_embedding=False,
            used_query_embedding=False,
            distance_by_id={},
        )

    def fake_rank(*, candidates, attribute_filters, user_text, distance_by_id, anchor_products, limit, exclude_product_ids):
        return SimpleNamespace(
            items=[first, second],
            meta={"recommendation_mode": "similar_items", "recommendation_ranked_count": 2},
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    pipeline._recommendation_service.expand_card_candidates = fake_expand  # type: ignore[method-assign]
    pipeline._recommendation_service.rank_canonical_products = fake_rank  # type: ignore[method-assign]

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="recommend titanium labrets", locale="en-US"),
        conversation_id=88,
        run_id="run-recommend",
        route_decision_override=_workflow_decision("recommendation"),
    )

    assert result.response.routing.workflow == "recommendation"
    assert len(result.response.product_carousel) == 2
    assert any(component.type.value == "recommendations" for component in result.response.components)
    assert "recommend" in result.response.reply_text.lower()
    assert result.debug.get("recommendation_mode_requested") == "similar_items"
