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
from app.services.chat.runtime import alias_cache, conversation_state
from app.services.chat.parsing import parser_rule_cache
from app.services.chat.parsing.detail_query_parser import DetailQuery
from app.services.chat.routing import routing_policy
from app.services.chat.routing.contracts import DecisionState
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.pipeline_runtime.setup import _merge_catalog_filter_hints
from app.services.chat.components.types import ComponentSource
from app.services.chat.presentation import clarify_policy
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


def _fallback_decision(*, reason: str = "pending_task_missing_slot") -> routing_policy.WorkflowDecision:
    return routing_policy.WorkflowDecision(
        workflow="fallback",
        source=ComponentSource.ERROR,
        needs_products=False,
        needs_knowledge=False,
        needs_clarification=True,
        store_overview_request=False,
        reason=reason,
        confidence=0.9,
    )


def test_catalog_filter_hints_require_explicit_opal_color() -> None:
    plain, plain_applied = _merge_catalog_filter_hints(
        current_filters={},
        user_text="product with sterilization with opal",
    )
    explicit, explicit_applied = _merge_catalog_filter_hints(
        current_filters={},
        user_text="product with sterilization with opal color",
    )

    assert plain == {}
    assert plain_applied is False
    assert explicit == {"opal_color": "opal"}
    assert explicit_applied is True


@pytest.mark.asyncio
async def test_component_pipeline_stores_pending_product_anchor_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)

    async def fake_generate_contextual_reply(*, kind, reply_language, payload):
        return str(payload.get("clarify_question") or "Which product are you asking about?")

    monkeypatch.setattr(clarify_policy, "generate_contextual_reply", fake_generate_contextual_reply)

    pipeline = ComponentPipeline(
        db=ConversationStateDB({"version": conversation_state.CONVERSATION_STATE_VERSION}),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    decision_state = DecisionState(
        internal_workflow="clarify",
        public_workflow="fallback",
        intent_confidence=0.9,
        retrieval_confidence=0.0,
        answerability="none",
        reason="missing product anchor",
        needs_products=False,
        needs_knowledge=False,
        intent="clarify",
        subintent="origin_question",
        user_goal="User wants product origin information.",
        response_policy="ask_clarifying_question",
        clarify_question="Which product are you asking about?",
        pending_task_type="product_origin_question",
        missing_slot="product_anchor",
    )

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="So is the product from China or made in Thailand?",
            locale="en-US",
        ),
        conversation_id=77,
        run_id="run-pending-store",
        route_decision_override=_fallback_decision(),
        detail_override=DetailQuery(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            is_detail_request=False,
            semantic_hints=[],
            clarify_focus="",
        ),
        decision_state_override=decision_state,
    )

    assert result.conversation_state is not None
    pending = dict(result.conversation_state.get("pending_task") or {})
    assert pending["task_type"] == "product_origin_question"
    assert pending["missing_slot"] == "product_anchor"
    assert pending["original_question"] == "So is the product from China or made in Thailand?"
    assert result.debug.get("pending_task_stored") is True


@pytest.mark.asyncio
async def test_component_pipeline_resumes_pending_product_anchor_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)

    product = canonical_product(
        sku="STEEL-1",
        name="Steel Product",
        attributes={"master_code": "STEEL-1", "material": "steel"},
    )
    pending_task = conversation_state.build_pending_task(
        task_type="product_origin_question",
        missing_slot="product_anchor",
        original_question="So is the product from China or made in Thailand?",
        original_intent="clarify",
        clarify_question="Which product are you asking about?",
    )

    class CatalogStub:
        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                cards=[product],
                product_ids=[str(product.product_id)],
                best_distance=0.1,
                distance_by_id={str(product.product_id): 0.1},
            )

        async def structured_search(self, **kwargs):
            return (
                SimpleNamespace(product_ids=[str(product.product_id)]),
                {},
            )

        async def structured_count(self, **kwargs):
            return 1

        async def smart_search(self, **kwargs):
            raise AssertionError("semantic fallback should not run in this test")

    pipeline = ComponentPipeline(
        db=ConversationStateDB(
            {
                "version": conversation_state.CONVERSATION_STATE_VERSION,
                "pending_task": pending_task,
            }
        ),
        catalog_search=CatalogStub(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    decision_state = DecisionState(
        internal_workflow="catalog_search",
        public_workflow="catalog",
        intent_confidence=0.92,
        retrieval_confidence=0.0,
        answerability="none",
        reason="product anchor supplied",
        needs_products=True,
        needs_knowledge=False,
        intent="product_information",
        subintent="product_search",
        product_query="Steel product",
        response_policy="answer_from_retrieved_data",
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Steel product", locale="en-US"),
        conversation_id=77,
        run_id="run-pending-resume",
        route_decision_override=_workflow_decision(),
        detail_override=DetailQuery(
            requested_fields=[],
            attribute_filters={"material": "steel"},
            wants_image=False,
            is_detail_request=False,
            semantic_hints=[],
            clarify_focus="",
        ),
        decision_state_override=decision_state,
    )

    assert result.debug.get("pending_task_resumed") is True
    assert result.conversation_state is not None
    assert dict(result.conversation_state.get("pending_task") or {}) == {}
    assert "manufacturing-origin data" in result.response.reply_text


@pytest.mark.asyncio
async def test_component_pipeline_resumes_pending_task_from_master_code_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)

    product = canonical_product(
        sku="DMBJ38-A09000",
        name="DMBJ38",
        attributes={"master_code": "DMBJ38", "material": "titanium g23"},
    )
    pending_task = conversation_state.build_pending_task(
        task_type="product_details_question",
        missing_slot="product_anchor",
        original_question="Can I see this product?",
        original_intent="clarify",
        clarify_question="Which product are you asking about?",
    )

    class CatalogStub:
        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                cards=[product],
                product_ids=[str(product.product_id)],
                best_distance=0.0,
                distance_by_id={str(product.product_id): 0.0},
            )

        async def structured_search(self, **kwargs):
            return (
                SimpleNamespace(product_ids=[str(product.product_id)]),
                {},
            )

        async def structured_count(self, **kwargs):
            return 1

        async def smart_search(self, **kwargs):
            raise AssertionError("semantic fallback should not run in this test")

    pipeline = ComponentPipeline(
        db=ConversationStateDB(
            {
                "version": conversation_state.CONVERSATION_STATE_VERSION,
                "pending_task": pending_task,
            }
        ),
        catalog_search=CatalogStub(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    decision_state = DecisionState(
        internal_workflow="clarify",
        public_workflow="catalog",
        intent_confidence=0.92,
        retrieval_confidence=0.0,
        answerability="none",
        reason="master code anchor supplied",
        needs_products=True,
        needs_knowledge=False,
        intent="clarify",
        subintent="product_search",
        product_query="DMBJ38",
        response_policy="ask_clarifying_question",
        clarify_question="Which product are you asking about?",
        pending_task_type="product_details_question",
        missing_slot="product_anchor",
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Can I see DMBJ38?", locale="en-US"),
        conversation_id=78,
        run_id="run-master-code-anchor",
        route_decision_override=_workflow_decision(),
        detail_override=DetailQuery(
            requested_fields=["attributes"],
            attribute_filters={},
            wants_image=False,
            is_detail_request=True,
            semantic_hints=[],
            clarify_focus="",
        ),
        decision_state_override=decision_state,
    )

    assert result.debug.get("pending_task_resumed") is True
    assert result.response.product_carousel
    assert not any(component.type.value == "clarify" for component in result.response.components)
    assert result.conversation_state is not None
    assert dict(result.conversation_state.get("pending_task") or {}) == {}


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
            captured["attribute_filters"] = dict(
                kwargs.get("attribute_filters")
                or kwargs.get("filters")
                or kwargs.get("hard_filters")
                or {}
            )
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

    async def fake_generate_contextual_reply(*, kind, reply_language, payload):
        return "What specifically do you need help with?"

    monkeypatch.setattr(clarify_policy, "generate_contextual_reply", fake_generate_contextual_reply)

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
    assert list(first.conversation_state.get("tone_recent") or []) == []

    db.payload = dict(first.conversation_state)
    second = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="help", locale="en-US"),
        conversation_id=77,
        run_id="run-tone-second",
        route_decision_override=fallback_decision,
    )

    assert second.response.reply_text == first.response.reply_text
    assert second.debug.get("tone_anti_repeat_applied") is False
    assert int(second.debug.get("tone_repeat_hit", 0) or 0) == 0


@pytest.mark.asyncio
async def test_component_pipeline_merges_prior_anchor_for_attribute_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)

    product = canonical_product(
        sku="LAB-GOLD-1",
        name="Gold Labret",
        attributes={"master_code": "LAB-1", "material": "gold", "jewelry_type": "labret"},
    )
    captured: dict[str, object] = {}

    class CatalogStub:
        async def vector_search(self, **kwargs):
            captured["attribute_filters"] = dict(
                kwargs.get("attribute_filters")
                or kwargs.get("filters")
                or kwargs.get("hard_filters")
                or {}
            )
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
        db=ConversationStateDB(
            {
                "version": 3,
                "last_attribute_filters": {
                    "material": "titanium",
                    "jewelry_type": "labret",
                },
            }
        ),
        catalog_search=CatalogStub(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="What about the gold one?", locale="en-US"),
        conversation_id=77,
        run_id="run-state-follow-up",
        route_decision_override=_workflow_decision(),
        detail_override=DetailQuery(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            is_detail_request=False,
            semantic_hints=[],
            clarify_focus="",
        ),
    )

    assert result.debug.get("conversation_state_filter_merge_applied") is True
    assert result.conversation_state is not None
    assert dict(result.conversation_state.get("last_attribute_filters") or {}) == {
        "material": "gold",
        "jewelry_type": "labret",
    }


@pytest.mark.asyncio
async def test_component_pipeline_active_product_answers_stock_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)
    product = canonical_product(
        sku="DMBJ38",
        name="Steel Labret",
        attributes={"master_code": "DMBJ38", "material": "steel", "jewelry_type": "labret"},
    )

    class CatalogStub:
        async def structured_search(self, **kwargs):
            raise AssertionError("active product detail follow-up should not run catalog search")

        async def structured_count(self, **kwargs):
            return 1

        async def vector_search(self, **kwargs):
            raise AssertionError("active product detail follow-up should not run vector search")

    pipeline = ComponentPipeline(
        db=ConversationStateDB(
            {
                "version": conversation_state.CONVERSATION_STATE_VERSION,
                "last_attribute_filters": {"material": "steel", "jewelry_type": "labret"},
                "active_product": {
                    "product_id": str(product.product_id),
                    "sku": "DMBJ38",
                    "master_code": "DMBJ38",
                    "name": "Steel Labret",
                    "source": "position_reference",
                    "confidence": 0.9,
                    "created_at": conversation_state.utc_timestamp(),
                    "updated_at": conversation_state.utc_timestamp(),
                },
                "displayed_products": [
                    {
                        "position": 1,
                        "product_id": str(product.product_id),
                        "sku": "DMBJ38",
                        "master_code": "DMBJ38",
                        "name": "Steel Labret",
                    }
                ],
            }
        ),
        catalog_search=CatalogStub(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        assert product_ids == [str(product.product_id)]
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Is it in stock?", locale="en-US"),
        conversation_id=77,
        run_id="run-active-stock",
        route_decision_override=_workflow_decision(),
        detail_override=DetailQuery(
            requested_fields=["stock"],
            attribute_filters={},
            wants_image=False,
            is_detail_request=True,
        ),
    )

    assert result.debug.get("context_used") is True
    assert result.debug.get("context_resolved_intent") == "inventory_check"
    assert result.debug.get("context_detail_followup_used") is True
    assert "stock" in result.response.reply_text.lower()
    assert result.conversation_state is not None
    assert result.conversation_state["active_product"]["sku"] == "DMBJ38"


@pytest.mark.asyncio
async def test_component_pipeline_ambiguous_product_pronoun_clarifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)

    class CatalogStub:
        async def structured_search(self, **kwargs):
            raise AssertionError("ambiguous product pronoun should not search")

        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            raise AssertionError("ambiguous product pronoun should not vector search")

    pipeline = ComponentPipeline(
        db=ConversationStateDB(
            {
                "version": conversation_state.CONVERSATION_STATE_VERSION,
                "last_product_ids": ["p1", "p2"],
                "displayed_products": [
                    {"position": 1, "product_id": "p1", "sku": "A1", "master_code": "A1", "name": "First Item"},
                    {"position": 2, "product_id": "p2", "sku": "B2", "master_code": "B2", "name": "Second Item"},
                ],
            }
        ),
        catalog_search=CatalogStub(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Is it in stock?", locale="en-US"),
        conversation_id=77,
        run_id="run-ambiguous-pronoun",
        route_decision_override=_workflow_decision(),
        detail_override=DetailQuery(
            requested_fields=["stock"],
            attribute_filters={},
            wants_image=False,
            is_detail_request=True,
            clarify_focus="",
        ),
    )

    assert result.debug.get("context_requires_clarification") is True
    assert result.debug.get("clarify_reason") == "context_needs_clarification"
    assert any(component.type.value == "clarify" for component in result.response.components)
