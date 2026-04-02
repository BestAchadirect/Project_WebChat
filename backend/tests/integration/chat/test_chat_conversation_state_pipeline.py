from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.services.ai.llm_service import llm_service
from app.services.chat.runtime import alias_cache
from app.services.chat.parsing import parser_rule_cache
from app.services.chat.routing import routing_policy
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.types import ComponentSource
from tests.fixtures.chat import KnowledgeStub, RedisStub
from tests.fixtures.persistence import ConversationStateDB


@pytest.fixture(autouse=True)
def chat_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_alias_map(db):
        return {}

    async def fake_get_parser_rules(db):
        return parser_rule_cache.get_cached_parser_rules()

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False)
    monkeypatch.setattr(alias_cache, "get_alias_map", fake_get_alias_map)
    monkeypatch.setattr(parser_rule_cache, "get_parser_rules", fake_get_parser_rules)
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)


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
async def test_component_pipeline_does_not_merge_filters_when_state_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False)

    product = canonical_product(
        sku="BR-002",
        name="Generic Belly Ring",
        attributes={"master_code": "BR-002", "material": "titanium"},
    )
    captured: dict[str, object] = {}

    class CatalogStub:
        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                cards=[product],
                product_ids=[str(product.product_id)],
                best_distance=0.1,
                distance_by_id={str(product.product_id): 0.1},
            )

        async def structured_search(self, **kwargs):
            captured["attribute_filters"] = dict(kwargs["attribute_filters"])
            return (
                SimpleNamespace(product_ids=[str(product.product_id)]),
                {},
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

    assert result.debug.get("conversation_state_enabled") is False
    assert result.debug.get("conversation_state_filter_merge_applied") is False
    assert result.conversation_state is None


@pytest.mark.asyncio
async def test_component_pipeline_tone_anti_repeat_persists_across_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_TONE_HUMANIZER_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_TONE_ANTI_REPEAT_WINDOW", 4)
    monkeypatch.setattr(settings, "CHAT_TONE_ENABLED_CHANNELS", "widget")

    class _StateResult:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def first(self):
            return (self._payload,)

    class _MutableConversationDB:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        async def execute(self, *args, **kwargs):
            return _StateResult(self.payload)

    fallback_decision = routing_policy.WorkflowDecision(
        workflow="fallback",
        source=ComponentSource.ERROR,
        needs_products=False,
        needs_knowledge=False,
        needs_clarification=True,
        store_overview_request=False,
        reason="test_fallback",
        confidence=1.0,
    )

    db = _MutableConversationDB({"version": 1})
    pipeline = ComponentPipeline(
        db=db,
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    first = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="help", locale="en-US"),
        conversation_id=77,
        run_id="run-tone-first",
        route_decision_override=fallback_decision,
    )
    assert first.conversation_state is not None
    assert list(first.conversation_state.get("tone_recent") or [])

    db.payload = dict(first.conversation_state)
    second = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="help", locale="en-US"),
        conversation_id=77,
        run_id="run-tone-second",
        route_decision_override=fallback_decision,
    )

    assert second.response.reply_text != first.response.reply_text
    assert second.debug.get("tone_anti_repeat_applied") is True
    assert int(second.debug.get("tone_repeat_hit", 0) or 0) >= 1
