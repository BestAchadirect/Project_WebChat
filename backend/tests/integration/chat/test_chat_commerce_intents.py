from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatRequest
from app.services.ai.llm_service import llm_service
from app.services.chat.routing import routing_policy
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
        needs_products=workflow == "catalog",
        needs_knowledge=workflow == "knowledge",
        needs_clarification=workflow == "fallback",
        store_overview_request=store_overview_request,
        reason="test_override",
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_component_pipeline_catalog_workflow_returns_catalog_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _canonical_product(sku="LAB-1", title="Titanium Labret 1", material="titanium")
    second = _canonical_product(sku="LAB-2", title="Titanium Labret 2", material="titanium")

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[str(first.product_id), str(second.product_id)]), {}

        async def structured_count(self, **kwargs):
            return 2

        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                cards=[],
                product_ids=[str(first.product_id), str(second.product_id)],
                distance_by_id={str(first.product_id): 0.08, str(second.product_id): 0.09},
                best_distance=0.08,
            )

        async def smart_search(self, **kwargs):
            raise AssertionError("semantic fallback should not run when structured catalog seeds exist")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [first, second], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="recommend titanium labrets", locale="en-US"),
        conversation_id=88,
        run_id="run-recommend",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert len(result.response.product_carousel) == 2
    assert "options" in result.response.reply_text.lower()
