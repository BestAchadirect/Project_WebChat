from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest, KnowledgeSource, ProductCard
from app.services.ai.llm_service import llm_service
from app.services.chat.runtime import alias_cache
from app.services.chat.parsing import parser_rule_cache
from app.services.chat.routing import routing_policy
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.types import ComponentSource
from app.services.chat.parsing.detail_query_parser import DetailQuery
from app.services.chat.retrieval.product_detail_resolver import ProductDetailResolver
from app.services.chat.retrieval.result_policy import classify_match_tier
from app.services.chat.presentation import component_contract
from app.services.chat.service import ChatService
from tests.fixtures.chat import DummyConversation, build_component_pipeline_result, patch_chat_service_lifecycle


class _RedisStub:
    async def get_json(self, key):
        return None

    async def set_json(self, key, value, ttl_seconds=0):
        return None


class _KnowledgeStub:
    async def search(self, *args, **kwargs):
        return []


@pytest.fixture(autouse=True)
def _stub_chat_alias_and_parser_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty_alias_map(db):
        return {}

    async def _empty_parser_rules(db):
        return []

    monkeypatch.setattr(alias_cache, "get_alias_map", _empty_alias_map)
    monkeypatch.setattr(parser_rule_cache, "get_parser_rules", _empty_parser_rules)


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


def _workflow_decision(
    workflow: str,
    *,
    store_overview_request: bool = False,
) -> routing_policy.WorkflowDecision:
    source = ComponentSource.KNOWLEDGE if workflow == "knowledge" else ComponentSource.SQL
    if workflow in {"fallback", "general_talking", "off_topic"}:
        source = ComponentSource.ERROR
    return routing_policy.WorkflowDecision(
        workflow=workflow,
        source=source,
        needs_products=workflow == "catalog",
        needs_knowledge=workflow == "knowledge",
        needs_clarification=workflow == "fallback",
        store_overview_request=store_overview_request,
        reason="test_override",
        confidence=1.0,
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


def test_result_policy_match_tier_allows_semantic_suggestion() -> None:
    assert classify_match_tier(structured_found=False, semantic_found=False) == "no_match"
    assert classify_match_tier(structured_found=False, semantic_found=True) == "semantic_suggestion"


@pytest.mark.asyncio
async def test_component_pipeline_hard_filter_no_match_uses_structured_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structured_calls = 0

    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(cards=[], distances=[], best_distance=None, distance_by_id={}, product_ids=[])

        async def structured_search(self, **kwargs):
            nonlocal structured_calls
            structured_calls += 1
            return SimpleNamespace(product_ids=[]), {}

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={"material": "titanium"},
            wants_image=False,
            is_detail_request=False,
        )

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="show titanium labrets", locale="en-US"),
        conversation_id=77,
        run_id="run-no-match",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert structured_calls >= 1
    assert "exact match" in result.response.reply_text.lower()
    assert result.debug.get("semantic_first_used") is True
    assert result.debug.get("semantic_structured_first_used") is True
    assert result.debug.get("semantic_structured_first_hit") is False
    assert result.debug.get("semantic_search_mode") == "vector_first"
    assert result.debug.get("component_source") == "sql"
    assert result.debug.get("match_tier") == "no_match"
    assert result.debug.get("retrieval_outcome", {}).get("match_tier") == "no_match"
    assert result.debug.get("retrieval_outcome", {}).get("needs_clarification") is True


@pytest.mark.asyncio
async def test_component_pipeline_design_discovery_uses_generic_structured_clarify_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(cards=[], distances=[], best_distance=None, distance_by_id={}, product_ids=[])

        async def structured_search(self, **kwargs):
            raise AssertionError("structured search should not run before semantic search")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            is_detail_request=False,
        )

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="What design do you have for your store?",
            locale="en-US",
        ),
        conversation_id=77,
        run_id="run-design-discovery",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert "material" in result.response.reply_text.lower() or "style" in result.response.reply_text.lower() or "gauge" in result.response.reply_text.lower()
    assert result.debug.get("clarify_reason") == "structured_no_match"
    assert result.debug.get("semantic_first_used") is True
    assert result.debug.get("clarify_mode") == "recoverable_product"
    assert result.debug.get("clarify_best_effort_help") is True


@pytest.mark.asyncio
async def test_component_pipeline_fake_nipple_triggers_suitability_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CatalogStub:
        async def structured_count(self, **kwargs):
            raise AssertionError("structured_count should not run when suitability gate triggers")

        async def vector_search(self, **kwargs):
            raise AssertionError("vector_search should not run when suitability gate triggers")

        async def structured_search(self, **kwargs):
            raise AssertionError("structured_search should not run when suitability gate triggers")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={},
            semantic_hints=["unclear body part"],
            clarify_focus="body_part",
            wants_image=False,
            is_detail_request=False,
        )

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="fake nipple", locale="en-US"),
        conversation_id=78,
        run_id="run-fake-nipple",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("clarify_reason") == "semantic_concept_unclear"
    assert result.response.routing.needs_clarification is True


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
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                product_ids=[str(product.product_id)],
                cards=[],
                distance_by_id={str(product.product_id): 0.08},
                best_distance=0.08,
            )

        async def structured_search(self, **kwargs):
            raise AssertionError("structured search should not run before semantic search")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
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
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="show me something nice", locale="en-US"),
        conversation_id=77,
        run_id="run-semantic",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert len(result.response.product_carousel) == 1
    assert result.debug.get("component_source") == "vector"
    assert result.debug.get("match_tier") == "semantic_suggestion"
    assert result.debug.get("semantic_first_used") is True
    assert result.debug.get("retrieval_quality") == "approximate"


@pytest.mark.asyncio
async def test_component_pipeline_broad_discovery_relaxes_hard_filter_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _canonical_product(
        sku="HELIX-16",
        title="Helix Option",
        attributes={"master_code": "HELIX-16", "material": "steel", "jewelry_type": "helix", "gauge": "16g"},
    )

    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                product_ids=[str(product.product_id)],
                cards=[_product_card(sku=product.sku, material="Steel")],
                distance_by_id={str(product.product_id): 0.24},
                best_distance=0.24,
            )

        async def structured_search(self, **kwargs):
            raise AssertionError("structured search should not run for relaxed broad discovery")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={"gauge": "14g"},
            wants_image=False,
            is_detail_request=False,
        )

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="show me something elegant for helix", locale="en-US"),
        conversation_id=77,
        run_id="run-broad-discovery-rescue",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert len(result.response.product_carousel) == 1
    assert any(component.type.value == "product_cards" for component in result.response.components)
    assert not any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("semantic_approximate_rescue_used") is True
    assert result.debug.get("retrieval_quality") == "approximate"
    assert result.debug.get("match_tier") == "semantic_suggestion"
    assert result.debug.get("semantic_guardrail_reason") == "hard_constraint_relaxed"


@pytest.mark.asyncio
async def test_component_pipeline_precision_sku_request_stays_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def smart_search(self, **kwargs):
            return SimpleNamespace(cards=[], product_ids=[], best_distance=None)

        async def vector_search(self, **kwargs):
            raise AssertionError("vector search should not run for strict SKU/detail flows")

        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[]), {}

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=["price"],
            attribute_filters={},
            wants_image=False,
            is_detail_request=True,
        )

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="price of XYZ-2", locale="en-US"),
        conversation_id=77,
        run_id="run-strict-sku",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert result.response.product_carousel == []
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("retrieval_quality") == "no_match"
    assert result.debug.get("match_tier") == "no_match"
    assert result.debug.get("semantic_approximate_rescue_used") is None


@pytest.mark.asyncio
async def test_component_pipeline_product_browse_reply_is_deterministic_without_llm_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _canonical_product(
        sku="LAB-14-STEEL-1",
        title="Labret 14g Steel",
        attributes={"master_code": "LAB-14-STEEL-1", "jewelry_type": "labret", "gauge": "14g", "material": "steel"},
    )
    search_card = ProductCard(
        id=product.product_id,
        object_id=product.sku,
        sku=product.sku,
        name=product.title,
        price=float(product.price),
        currency=product.currency,
        stock_status="in_stock" if product.in_stock else "out_of_stock",
        attributes={
            "jewelry_type": "labret",
            "gauge": "14g",
            "material": "steel",
        },
    )

    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 1

        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                product_ids=[str(search_card.id)],
                cards=[search_card],
                distance_by_id={str(search_card.id): 0.08},
                best_distance=0.08,
            )

        async def structured_search(self, **kwargs):
            raise AssertionError("structured search should not run before semantic search")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={"jewelry_type": "labret", "gauge": "14g", "material": "steel"},
            wants_image=False,
            is_detail_request=False,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    async def fake_generate_chat_json(*, messages, **kwargs):
        return {"reply": "Steel material labrets are available in a range of styles."}

    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Give me a Labret with 14g with steel", locale="en-US"),
        conversation_id=77,
        run_id="run-deterministic-browse",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert result.llm_calls == 1
    assert result.debug.get("component_source") == "vector"
    assert result.debug.get("match_tier") == "semantic_suggestion"
    assert "steel material" in result.response.reply_text.lower()
    assert component_contract.follow_up_questions_from_response(result.response) == []


@pytest.mark.asyncio
async def test_component_pipeline_semantic_hint_no_match_returns_focused_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_card = ProductCard(
        id=uuid4(),
        object_id="BROAD-1",
        sku="BROAD-1",
        name="Broad Steel Item",
        price=12.0,
        currency="USD",
        stock_status="in_stock",
        attributes={"material": "steel", "jewelry_type": "labret"},
    )

    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                product_ids=[str(search_card.id)],
                cards=[search_card],
                distance_by_id={str(search_card.id): 0.08},
                best_distance=0.08,
            )

        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[]), {}

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={},
            semantic_hints=["sterilization"],
            clarify_focus="condition",
            wants_image=False,
            is_detail_request=False,
        )

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="I want to buy sterilization product", locale="en-US"),
        conversation_id=77,
        run_id="run-semantic-hint-clarify",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.response.product_carousel == []
    assert result.debug.get("clarify_reason") == "semantic_concept_unclear"
    assert result.debug.get("semantic_guardrail_reason") == "semantic_hint_clarify"
    assert result.debug.get("semantic_hint_clarify_used") is True
    assert result.response.reply_text.lower().startswith("what condition")
    assert result.debug.get("clarify_mode") == "strict_ambiguity"
    assert result.debug.get("clarify_best_effort_help") is False


@pytest.mark.asyncio
async def test_component_pipeline_semantic_hint_no_match_returns_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _canonical_product(
        sku="STERILE-1",
        title="Sterilized Piercing Supply",
        attributes={"master_code": "STERILE-1", "category": "EO gas sterilized piercing"},
    )
    search_card = ProductCard(
        id=product.product_id,
        object_id=product.sku,
        sku=product.sku,
        name=product.title,
        description=product.description,
        price=float(product.price),
        currency=product.currency,
        stock_status="in_stock",
        search_text="eo gas sterilized piercing supply surgical steel",
        attributes={"category": "EO gas sterilized piercing"},
    )

    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                product_ids=[],
                cards=[],
                distance_by_id={},
                best_distance=None,
            )

        async def lexical_search(self, **kwargs):
            return SimpleNamespace(
                product_ids=[str(search_card.id)],
                cards=[search_card],
                distance_by_id={str(search_card.id): 0.85},
                best_distance=0.85,
            )

        async def structured_search(self, **kwargs):
            raise AssertionError("structured search should not run before lexical rescue")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={},
            semantic_hints=["sterilization"],
            clarify_focus="condition",
            wants_image=False,
            is_detail_request=False,
        )

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="I want to buy sterilization product", locale="en-US"),
        conversation_id=77,
        run_id="run-semantic-lexical-rescue",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert not result.response.product_carousel
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("lexical_search_used") is None
    assert result.debug.get("lexical_rescue_used") is None
    assert result.debug.get("semantic_hint_clarify_used") is True


@pytest.mark.asyncio
async def test_component_pipeline_detail_timeout_blocks_broad_vector_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CatalogStub:
        async def structured_count(self, **kwargs):
            raise AssertionError("catalog search should not run when detail parsing timed out")

        async def vector_search(self, **kwargs):
            raise AssertionError("vector search should not run when detail parsing timed out")

        async def lexical_search(self, **kwargs):
            raise AssertionError("lexical search should not run when detail parsing timed out")

        async def structured_search(self, **kwargs):
            raise AssertionError("structured search should not run when detail parsing timed out")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={},
            semantic_hints=[],
            clarify_focus="",
            wants_image=False,
            is_detail_request=False,
            parse_failed=True,
            parse_error="Request timed out.",
            extraction_debug={"llm_detail_query_error": "Request timed out."},
        )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("attribute list target inference should not run when detail parsing timed out")

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    monkeypatch.setattr(
        "app.services.chat.components.pipeline_runtime.core.infer_attribute_list_target",
        fail_if_called,
    )

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-parse-timeout",
            message="Do you have any sterilization product?",
            locale="en-US",
        ),
        conversation_id=77,
        run_id="run-detail-timeout-clarify",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert result.response.routing.needs_clarification is True
    assert result.response.product_carousel == []
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("detail_parse_failed") is True
    assert result.debug.get("catalog_retrieval_blocked_reason") == "detail_extraction_failed"
    assert result.debug.get("clarify_reason") == "semantic_concept_unclear"


@pytest.mark.asyncio
async def test_component_pipeline_sterilization_with_opal_returns_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(product_ids=[], cards=[], distance_by_id={}, best_distance=None)

        async def lexical_search(self, **kwargs):
            return SimpleNamespace(product_ids=[], cards=[], distance_by_id={}, best_distance=None)

        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[]), {}

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={},
            semantic_hints=[],
            clarify_focus="condition",
            wants_image=False,
            is_detail_request=False,
        )

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Can i see sterilization with opal?", locale="en-US"),
        conversation_id=77,
        run_id="run-sterilization-opal-clarify",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert not result.response.product_carousel
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("clarify_reason") == "semantic_concept_unclear"
    assert result.debug.get("semantic_guardrail_reason") == "semantic_hint_clarify"
    assert result.debug.get("semantic_hint_clarify_used") is True


@pytest.mark.asyncio
async def test_component_pipeline_semantic_ambiguity_skips_attribute_list_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(product_ids=[], cards=[], distance_by_id={}, best_distance=None)

        async def lexical_search(self, **kwargs):
            return SimpleNamespace(product_ids=[], cards=[], distance_by_id={}, best_distance=None)

        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[]), {}

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_parse(*, user_text: str, nlu_data, **kwargs):
        return DetailQuery(
            requested_fields=[],
            attribute_filters={},
            semantic_hints=["sterilization"],
            clarify_focus="condition",
            wants_image=False,
            is_detail_request=False,
        )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("attribute list target inference should be skipped for semantic ambiguity")

    async def fail_attribute_list_workflow(*args, **kwargs):
        raise AssertionError("attribute list workflow should be skipped for semantic ambiguity")

    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    monkeypatch.setattr(
        "app.services.chat.components.pipeline_runtime.core.infer_attribute_list_target",
        fail_if_called,
    )
    monkeypatch.setattr(ComponentPipeline, "_handle_attribute_list_workflow", fail_attribute_list_workflow)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Can i see product with sterilization?", locale="en-US"),
        conversation_id=77,
        run_id="run-semantic-ambiguity-skip-attribute-list",
        route_decision_override=_workflow_decision("catalog"),
    )

    assert result.response.routing.workflow == "catalog"
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("attribute_list_target_source") is None
    assert result.debug.get("clarify_reason") == "semantic_concept_unclear"


@pytest.mark.asyncio
async def test_component_pipeline_high_risk_knowledge_error_returns_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def failing_generate_embedding(text: str):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(llm_service, "generate_embedding", failing_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="What is your shipping policy?", locale="en-US"),
        conversation_id=77,
        run_id="run-knowledge-error",
        route_decision_override=_workflow_decision("knowledge"),
    )

    assert result.response.routing.workflow == "knowledge"
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("component_knowledge_fail_soft") is True
    assert result.debug.get("clarify_reason") == "knowledge_unavailable"
    follow_ups = [item.lower() for item in component_contract.follow_up_questions_from_response(result.response)]
    assert follow_ups == []
    assert result.debug.get("clarify_mode") == "strict_knowledge"
    assert result.debug.get("clarify_best_effort_help") is True


@pytest.mark.asyncio
async def test_component_pipeline_high_risk_knowledge_with_weak_sources_returns_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _WeakKnowledgeStub:
        async def search(self, *args, **kwargs):
            return [
                KnowledgeSource(
                    source_id="kb-1",
                    title="Shipping",
                    content_snippet="General shipping information.",
                    relevance=0.2,
                )
            ]

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_WeakKnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    async def fake_knowledge_answer_once(**kwargs):
        return "Shipping varies by destination.", False

    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(pipeline, "_knowledge_answer_once", fake_knowledge_answer_once)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="How can I contact your sales team?", locale="en-US"),
        conversation_id=77,
        run_id="run-knowledge-weak",
        route_decision_override=_workflow_decision("knowledge"),
    )

    assert result.response.routing.workflow == "knowledge"
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("component_knowledge_needs_clarification") is True
    assert result.debug.get("clarify_reason") == "knowledge_needs_clarification"
    assert result.debug.get("knowledge_clarify_focus") == "contact"
    assert "email" in result.response.reply_text.lower() or "phone" in result.response.reply_text.lower()
    follow_ups = [item.lower() for item in component_contract.follow_up_questions_from_response(result.response)]
    assert follow_ups == []
    assert result.debug.get("clarify_mode") == "strict_knowledge"
    assert result.debug.get("clarify_best_effort_help") is True


@pytest.mark.asyncio
async def test_component_pipeline_store_overview_knowledge_passes_retrieval_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _KnowledgeStub:
        async def search(self, *args, **kwargs):
            captured["store_overview_request"] = kwargs.get("store_overview_request")
            return [
                KnowledgeSource(
                    source_id="kb-contact",
                    title="How can I contact Acha?",
                    category="Contact",
                    content_snippet="Acha Co., Ltd. showroom address in Bangkok with phone details.",
                    relevance=0.35,
                    distance=0.65,
                )
            ]

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    async def fake_knowledge_answer_once(**kwargs):
        captured["answer_store_overview_request"] = kwargs.get("store_overview_request")
        return "Acha Co., Ltd. has a showroom in Bangkok.", False

    async def fake_plan_knowledge_retrieval(**kwargs):
        return {
            "query_text": "What is your company?",
            "topic": "store_overview",
            "must_tags": [],
            "boost_tags": ["store_overview"],
            "required_evidence": ["company overview"],
            "forbidden_topics": [],
            "store_overview_request": True,
            "answer_style": {"max_sentences": 2},
        }

    async def fake_select_knowledge_sources_with_llm(**kwargs):
        return list(kwargs.get("candidates", []) or [])[:3]

    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(pipeline, "_knowledge_answer_once", fake_knowledge_answer_once)
    monkeypatch.setattr(pipeline, "_plan_knowledge_retrieval", fake_plan_knowledge_retrieval)
    monkeypatch.setattr(pipeline, "_select_knowledge_sources_with_llm", fake_select_knowledge_sources_with_llm)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="What is your company?", locale="en-US"),
        conversation_id=77,
        run_id="run-store-overview-knowledge",
        route_decision_override=_workflow_decision("knowledge", store_overview_request=True),
    )

    assert result.response.routing.workflow == "knowledge"
    assert captured["store_overview_request"] is True
    assert captured["answer_store_overview_request"] is True


@pytest.mark.asyncio
async def test_component_pipeline_off_topic_uses_terminal_llm_reply_without_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    captured: dict[str, object] = {}

    async def fake_generate_chat_json(*, messages, usage_kind=None, **kwargs):
        captured["usage_kind"] = usage_kind
        captured["workflow"] = json.loads(str(messages[1].get("content") or "{}")).get("workflow")
        return {"reply": "I can't help with coding here, but I can help with body jewelry products and store policies."}

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Can you write Python code for me?", locale="en-US"),
        conversation_id=77,
        run_id="run-off-topic",
        route_decision_override=_workflow_decision("off_topic"),
    )

    reply = str(result.response.reply_text or "")
    assert result.response.routing.workflow == "off_topic"
    assert result.debug.get("component_source") == "error"
    assert result.debug.get("terminal_reply_source") == "llm"
    assert result.embedding_calls == 0
    assert result.llm_calls == 2
    assert "I can't help with coding here, but I can help with body jewelry products and store policies." in reply
    assert captured["usage_kind"] == "chat_component_off_topic_copy"
    assert captured["workflow"] == "off_topic"
    component_types = [component.type.value for component in result.response.components]
    assert "knowledge_answer" not in component_types
    assert component_types == ["assistant_message", "query_summary"]


@pytest.mark.asyncio
async def test_component_pipeline_general_talking_uses_terminal_llm_reply_without_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    captured: dict[str, object] = {}

    async def fake_generate_chat_json(*, messages, usage_kind=None, **kwargs):
        payload = json.loads(str(messages[1].get("content") or "{}"))
        captured["usage_kind"] = usage_kind
        captured["workflow"] = payload.get("workflow")
        return {"reply": "Hi, I can help with body jewelry products, materials, sizes, stock, pricing, and store info."}

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Hi there", locale="en-US"),
        conversation_id=77,
        run_id="run-general-talking",
        route_decision_override=_workflow_decision("general_talking"),
    )

    reply = str(result.response.reply_text or "")
    scope_candidates = [
        "body jewelry",
        "materials",
        "sizes",
        "stock",
        "pricing",
        "store info",
        "Achadirect support",
    ]

    assert result.response.routing.workflow == "general_talking"
    assert result.debug.get("component_source") == "error"
    assert result.debug.get("terminal_reply_source") == "llm"
    assert result.embedding_calls == 0
    assert result.llm_calls == 2
    assert any(candidate in reply.lower() for candidate in scope_candidates)
    assert captured["usage_kind"] == "chat_component_default_copy"
    assert captured["workflow"] == "general_talking"


@pytest.mark.asyncio
async def test_component_pipeline_off_topic_uses_terminal_llm_with_requested_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    captured = {"called": 0, "locale": ""}

    async def fake_generate_chat_json(*, messages, **kwargs):
        payload = json.loads(str(messages[1].get("content") or "{}"))
        captured["called"] += 1
        captured["locale"] = str(payload.get("locale") or "")
        thai = f"{chr(0x0E04)}{chr(0x0E48)}{chr(0x0E30)}"
        mojibake = bytes([0xE0, 0xB8, 0x84, 0xE0, 0xB9, 0x88, 0xE0, 0xB8, 0xB0]).decode("cp1252")
        return {"reply": f"Sawasdee ka {thai} {mojibake}, I can help with products and store info."}

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Hi there", locale="th-TH"),
        conversation_id=77,
        run_id="run-general-talking-th",
        route_decision_override=_workflow_decision("general_talking"),
    )

    reply = str(result.response.reply_text or "")
    assert result.response.routing.workflow == "general_talking"
    assert result.debug.get("component_source") == "error"
    assert result.debug.get("terminal_reply_source") == "llm"
    assert result.embedding_calls == 0
    assert result.llm_calls == 2
    assert captured["called"] == 2
    assert captured["locale"] == "th-TH"
    assert "ค่ะ" in reply


@pytest.mark.asyncio
async def test_component_pipeline_off_topic_uses_terminal_llm_for_any_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    captured = {"called": 0, "locale": ""}

    async def fake_generate_chat_json(*, messages, **kwargs):
        payload = json.loads(str(messages[1].get("content") or "{}"))
        captured["called"] += 1
        captured["locale"] = str(payload.get("locale") or "")
        return {"reply": "Hola, puedo ayudarte con productos de joyeria corporal y politicas de la tienda."}

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Hi there", locale="es-ES"),
        conversation_id=77,
        run_id="run-general-talking-es",
        route_decision_override=_workflow_decision("general_talking"),
    )

    reply = str(result.response.reply_text or "")
    assert result.response.routing.workflow == "general_talking"
    assert result.debug.get("component_source") == "error"
    assert result.debug.get("terminal_reply_source") == "llm"
    assert result.embedding_calls == 0
    assert result.llm_calls == 2
    assert captured["called"] == 2
    assert captured["locale"] == "es-ES"
    assert "Hola" in reply


@pytest.mark.asyncio
async def test_component_pipeline_fallback_vague_store_request_uses_scope_clarify_message() -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="help", locale="en-US"),
        conversation_id=77,
        run_id="run-routing-fallback",
        route_decision_override=_workflow_decision("fallback"),
    )

    assert result.response.routing.workflow == "fallback"
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.response.reply_text
    assert any(
        term in result.response.reply_text.lower()
        for term in ("product", "body jewelry", "store", "shipping", "contact")
    )
    assert result.debug.get("clarify_reason") == "fallback_vague_store_request"
    assert result.debug.get("tone_key") == ""
    assert result.debug.get("clarify_category") == "vague_store_request"
    assert result.debug.get("clarify_mode") == "broad_help"
    assert result.debug.get("clarify_best_effort_help") is True


@pytest.mark.asyncio
async def test_component_pipeline_fallback_gibberish_asks_rephrase() -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="asdfafafdas", locale="en-US"),
        conversation_id=77,
        run_id="run-fallback-gibberish",
        route_decision_override=_workflow_decision("fallback"),
    )

    assert result.response.routing.workflow == "fallback"
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert "rephrase" in result.response.reply_text.lower() or "type it again" in result.response.reply_text.lower()
    assert result.debug.get("clarify_reason") == "fallback_gibberish"
    assert result.debug.get("tone_key") == ""
    assert result.debug.get("clarify_mode") == "gibberish"
    assert result.debug.get("clarify_best_effort_help") is False


@pytest.mark.asyncio
@pytest.mark.performance
async def test_chat_service_component_path_is_repeatable_under_repeated_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        del self, conversation_id, run_id, kwargs
        return build_component_pipeline_result(
            request=request,
            conversation_id=77,
            reply_text="I found titanium labrets.",
            response_workflow="catalog",
            source="sql",
            response_debug={"reply_mode": "deterministic_product"},
            product_carousel=[
                {
                    "id": "33333333-3333-3333-3333-333333333333",
                    "sku": "EVAL-TI-LAB-1",
                    "name": "Titanium Labret",
                    "price": 19.5,
                    "currency": "USD",
                    "stock_status": "in_stock",
                    "attributes": {"material": "titanium"},
                }
            ],
        )

    patch_chat_service_lifecycle(
        monkeypatch,
        conversation=DummyConversation(conversation_id=77),
    )
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    service = ChatService(db=object())
    snapshots: list[dict[str, object]] = []
    for _ in range(3):
        response = await service.process_chat(
            ChatRequest(user_id="perf-user", message="show titanium labrets", locale="en-US"),
            channel="widget",
        )
        snapshots.append(
            {
                "workflow": response.routing.workflow,
                "reply_text": response.reply_text,
                "product_skus": [card.sku for card in response.product_carousel],
                "source_titles": [source.title for source in response.sources],
                "llm_calls": int(getattr(response.meta, "llm_calls", 0) or 0),
                "embedding_calls": int(getattr(response.meta, "embedding_calls", 0) or 0),
                "latency_span_keys": sorted(dict(response.debug or {}).get("latency_spans", {}).keys()),
                "latency_span_count": len(dict(response.debug or {}).get("latency_spans", {})),
            }
        )
        assert response.meta is not None
        assert int(getattr(response.meta, "llm_calls", 0) or 0) == 0
        assert int(getattr(response.meta, "embedding_calls", 0) or 0) == 0
        latency_spans = dict(response.debug or {}).get("latency_spans", {})
        assert isinstance(latency_spans, dict)
        assert latency_spans
        assert all(isinstance(value, (int, float)) and value >= 0 for value in latency_spans.values())

    assert snapshots[0] == snapshots[1] == snapshots[2]


