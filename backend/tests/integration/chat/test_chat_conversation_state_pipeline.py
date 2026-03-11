from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.services.chat import routing_policy
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.types import ComponentSource
from tests.fixtures.chat import KnowledgeStub, RedisStub
from tests.fixtures.persistence import ConversationStateDB


@pytest.fixture(autouse=True)
def chat_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_SQL_FIRST_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False)


def canonical_product(*, sku: str, name: str, attributes: dict | None = None) -> CanonicalProduct:
    return CanonicalProduct(
        product_id=uuid4(),
        sku=sku,
        title=name,
        price=Decimal("12.50"),
        currency="USD",
        in_stock=True,
        stock_qty=5,
        material=str((attributes or {}).get("material") or "Titanium"),
        gauge="14g",
        image_url=None,
        description=name,
        attributes=attributes or {},
        product_url="https://example.com/product",
    )


def _workflow_decision() -> routing_policy.WorkflowDecision:
    return routing_policy.WorkflowDecision(
        workflow="catalog",
        source=ComponentSource.SQL,
        needs_products=True,
        needs_knowledge=False,
        needs_clarification=False,
        store_overview_request=False,
        reason="test_override",
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_component_pipeline_merges_filters_from_conversation_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)

    prior_state = {
        "version": 1,
        "last_attribute_filters": {
            "material": "titanium",
            "jewelry_type": "belly ring",
        },
    }
    product = canonical_product(
        sku="BR-001",
        name="Titanium Belly Ring",
        attributes={"master_code": "BR-001", "material": "titanium", "jewelry_type": "belly ring"},
    )
    captured: dict[str, object] = {}

    class CatalogStub:
        async def structured_search(self, **kwargs):
            captured["attribute_filters"] = dict(kwargs["attribute_filters"])
            return (
                SimpleNamespace(product_ids=[str(product.product_id)]),
                {"structured_read_mode": "eav", "projection_hit": False},
            )

        async def structured_count(self, **kwargs):
            return 1

        async def smart_search(self, **kwargs):
            raise AssertionError("semantic fallback should not run for merged structured filters")

    pipeline = ComponentPipeline(
        db=ConversationStateDB(prior_state),
        catalog_search=CatalogStub(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        assert product_ids == [str(product.product_id)]
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="cheaper ones", locale="en-US"),
        conversation_id=77,
        run_id="run-state-merge",
        route_decision_override=_workflow_decision(),
    )

    assert captured["attribute_filters"] == {
        "material": "titanium",
        "jewelry_type": "belly ring",
    }
    assert result.debug.get("conversation_state_filter_merge_applied") is True
    assert result.debug.get("conversation_state_loaded_version") == 1
    assert result.conversation_state is not None
    assert result.conversation_state["last_attribute_filters"] == {
        "material": "titanium",
        "jewelry_type": "belly ring",
    }
    assert result.conversation_state["last_product_ids"] == [str(product.product_id)]
    assert result.conversation_state["last_route"] == "catalog"


@pytest.mark.asyncio
async def test_component_pipeline_does_not_merge_filters_when_state_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False)

    product = canonical_product(
        sku="BR-002",
        name="Generic Belly Ring",
        attributes={"master_code": "BR-002", "material": "titanium"},
    )
    captured: dict[str, object] = {}

    class CatalogStub:
        async def structured_search(self, **kwargs):
            captured["attribute_filters"] = dict(kwargs["attribute_filters"])
            return (
                SimpleNamespace(product_ids=[str(product.product_id)]),
                {"structured_read_mode": "eav", "projection_hit": False},
            )

        async def structured_count(self, **kwargs):
            return 1

        async def smart_search(self, **kwargs):
            raise AssertionError("semantic fallback should not run in this test")

    pipeline = ComponentPipeline(
        db=ConversationStateDB({"version": 1, "last_attribute_filters": {"material": "titanium"}}),
        catalog_search=CatalogStub(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="cheaper ones", locale="en-US"),
        conversation_id=77,
        run_id="run-state-disabled",
        route_decision_override=_workflow_decision(),
    )

    assert captured["attribute_filters"] == {}
    assert result.debug.get("conversation_state_enabled") is False
    assert result.debug.get("conversation_state_filter_merge_applied") is False
    assert result.conversation_state is None
