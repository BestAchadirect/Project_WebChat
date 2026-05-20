from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.services.chat.routing import routing_policy
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.parsing.detail_query_parser import DetailQuery
from app.services.chat.retrieval.product_detail_resolver import DetailResolutionResult
from app.services.chat.presentation import component_contract
from app.services.chat.routing.contracts import DecisionState
from app.services.chat.runtime import conversation_state


class _RedisStub:
    async def get_json(self, key):
        return None

    async def set_json(self, key, value, ttl_seconds=0):
        return None


class _KnowledgeStub:
    async def search(self, *args, **kwargs):
        return []


def _canonical_product(
    *,
    sku: str,
    title: str,
    image_url: str | None = None,
    attributes: dict | None = None,
) -> CanonicalProduct:
    return CanonicalProduct(
        product_id=uuid4(),
        sku=sku,
        title=title,
        price=Decimal("1.59"),
        currency="USD",
        in_stock=True,
        stock_qty=10,
        material="Black Steel",
        gauge="25mm",
        image_url=image_url,
        description=title,
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
async def test_component_pipeline_detail_mode_price_stock_returns_product_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", True)
    product = _canonical_product(
        sku="BB-25-BLK",
        title="Black Barbell 25mm",
        attributes={"master_code": "BB-25-BLK", "jewelry_type": "barbell", "color": "black", "gauge": "25mm"},
    )

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[str(product.product_id)]), {}

        async def structured_count(self, **kwargs):
            return 1

        async def smart_search(self, **kwargs):
            raise AssertionError("detail mode should not use semantic fallback when structured results exist")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_parse(*, user_text: str, nlu_data, **_):
        return DetailQuery(
            requested_fields=["price", "stock"],
            attribute_filters={"jewelry_type": "barbell", "color": "black", "gauge": "25mm"},
            wants_image=False,
            is_detail_request=True,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="price and stock for black barbell 25mm", locale="en-US"),
        conversation_id=9,
        run_id="run-detail",
        route_decision_override=_workflow_decision(),
    )

    assert result.detail_mode_triggered is True
    assert result.response.routing.workflow == "catalog"
    assert len(result.response.product_carousel) == 1
    assert any(component.type.value == "product_detail" for component in result.response.components)
    assert "Price:" in result.response.reply_text
    assert "Stock:" in result.response.reply_text
    assert result.debug.get("detail_match_count") == 1


@pytest.mark.asyncio
async def test_component_primary_detail_path_runs_even_if_legacy_flags_are_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", False)
    product = _canonical_product(
        sku="IMG-1",
        title="Titanium Labret",
        image_url="https://example.com/image.jpg",
        attributes={"master_code": "IMG-1", "jewelry_type": "labret", "material": "titanium"},
    )

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[str(product.product_id)]), {}

        async def structured_count(self, **kwargs):
            return 1

        async def smart_search(self, **kwargs):
            raise AssertionError("detail mode should stay in the component path")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_parse(*, user_text: str, nlu_data, **_):
        return DetailQuery(
            requested_fields=["image"],
            attribute_filters={"jewelry_type": "labret"},
            wants_image=True,
            is_detail_request=True,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="show image for this labret", locale="en-US"),
        conversation_id=9,
        run_id="run-detail-component-primary",
        route_decision_override=_workflow_decision(),
    )

    assert result.detail_mode_triggered is True
    assert any(component.type.value == "product_detail" for component in result.response.components)
    assert result.response.product_carousel[0].sku == "IMG-1"


@pytest.mark.asyncio
async def test_component_pipeline_compare_multiple_master_codes_returns_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", True)
    left = _canonical_product(
        sku="DMBJ38-A09000",
        title="DMBJ38",
        attributes={"master_code": "DMBJ38"},
    )
    right = _canonical_product(
        sku="BRUBN2-F04000",
        title="BRUBN2",
        attributes={"master_code": "BRUBN2"},
    )

    class _CatalogStub:
        async def structured_search(self, *, sku_token, attribute_filters, limit, candidate_cap, catalog_version, return_ids_only=False):
            del attribute_filters, candidate_cap, catalog_version, return_ids_only
            if str(sku_token).lower() == "dmbj38":
                return SimpleNamespace(cards=[left], product_ids=[str(left.product_id)]), {}
            if str(sku_token).lower() == "brubn2":
                return SimpleNamespace(cards=[right], product_ids=[str(right.product_id)]), {}
            return SimpleNamespace(cards=[], product_ids=[]), {}

        async def structured_count(self, **kwargs):
            return 2

        async def smart_search(self, **kwargs):
            raise AssertionError("compare should not use semantic fallback")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    detail = DetailQuery(
        requested_fields=["price", "stock"],
        attribute_filters={},
        wants_image=False,
        is_detail_request=True,
    )

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="compare DMBJ38 vs BRUBN2",
            locale="en-US",
        ),
        conversation_id=10,
        run_id="run-compare",
        route_decision_override=_workflow_decision(),
        detail_override=detail,
    )

    component_types = [component.type.value for component in list(result.response.components or [])]
    assert result.detail_mode_triggered is False
    assert result.response.routing.workflow == "catalog"
    assert "product_cards" in component_types
    assert len(result.response.product_carousel) == 2
    assert "compare" in result.response.reply_text.lower()
    assert "DMBJ38" in result.response.reply_text
    assert "BRUBN2" in result.response.reply_text


@pytest.mark.asyncio
async def test_component_pipeline_detail_mode_appends_related_opal_ball_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", True)
    seed_products = [
        _canonical_product(
            sku="RSSELO20-A01",
            title="RSSELO20",
            attributes={"master_code": "RSSELO20", "jewelry_type": "seamless ring", "material": "925 sterling silver"},
        ),
        _canonical_product(
            sku="RSSELO20-A02",
            title="RSSELO20",
            attributes={"master_code": "RSSELO20", "jewelry_type": "seamless ring", "material": "925 sterling silver"},
        ),
        _canonical_product(
            sku="RSSELO20-A03",
            title="RSSELO20",
            attributes={"master_code": "RSSELO20", "jewelry_type": "seamless ring", "material": "925 sterling silver"},
        ),
    ]
    related_products = [
        _canonical_product(
            sku="AGSELO20-A01",
            title="AGSELO20",
            attributes={"master_code": "AGSELO20", "jewelry_type": "seamless ring", "material": "925 sterling silver"},
        ),
        _canonical_product(
            sku="AGSELO22-A01",
            title="AGSELO22",
            attributes={"master_code": "AGSELO22", "jewelry_type": "seamless ring", "material": "925 sterling silver"},
        ),
    ]

    class _CatalogStub:
        async def structured_search(self, *, sku_token, attribute_filters, limit, candidate_cap, catalog_version, return_ids_only=False):
            del sku_token, attribute_filters, limit, candidate_cap, catalog_version, return_ids_only
            return SimpleNamespace(product_ids=[str(item.product_id) for item in seed_products]), {}

        async def structured_count(self, **kwargs):
            return len(seed_products)

        async def vector_search(self, *, query_embedding, limit, candidate_limit):
            del query_embedding, limit, candidate_limit
            return SimpleNamespace(
                cards=list(seed_products),
                product_ids=[str(item.product_id) for item in seed_products],
                best_distance=0.0,
                distance_by_id={str(item.product_id): 0.0 for item in seed_products},
            )

        async def lexical_search(self, *, query_text, limit=10, candidate_limit=None):
            del limit, candidate_limit
            assert "opal" in str(query_text).lower()
            return SimpleNamespace(
                cards=list(related_products),
                distances=[],
                best_distance=0.0,
                distance_by_id={str(item.product_id): 0.0 for item in related_products},
            )

        async def smart_search(self, **kwargs):
            raise AssertionError("detail mode should not use semantic fallback")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        del component_types, component_cache, kwargs
        resolved = [item for item in seed_products if str(item.product_id) in {str(raw) for raw in product_ids}]
        return resolved, {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_parse(*, user_text: str, nlu_data, **_):
        del user_text, nlu_data
        return DetailQuery(
            requested_fields=[],
            attribute_filters={"jewelry_type": "seamless ring"},
            wants_image=False,
            is_detail_request=True,
            semantic_hints=["opal ball"],
            clarify_focus="",
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="Now i want it with opal ball",
            locale="en-US",
        ),
        conversation_id=11,
        run_id="run-detail-related",
        route_decision_override=_workflow_decision(),
    )

    product_carousel = list(result.response.product_carousel or [])
    master_codes = [str(getattr(card, "attributes", {}).get("master_code", "") or "") for card in product_carousel]

    assert result.detail_mode_triggered is True
    assert len(product_carousel) == 5
    assert master_codes[:3] == ["RSSELO20", "RSSELO20", "RSSELO20"]
    assert "AGSELO20" in master_codes
    assert "AGSELO22" in master_codes
    assert "related options" in result.response.reply_text.lower()
    assert result.debug.get("detail_related_products_used") is True


@pytest.mark.asyncio
async def test_component_pipeline_related_product_followup_uses_last_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _canonical_product(
        sku="SEED-1",
        title="Seed Product",
        attributes={"master_code": "SEED-1", "jewelry_type": "ring"},
    )
    related = [
        _canonical_product(
            sku="REL-1",
            title="Related Product 1",
            attributes={"master_code": "REL-1", "jewelry_type": "ring"},
        ),
        _canonical_product(
            sku="REL-2",
            title="Related Product 2",
            attributes={"master_code": "REL-2", "jewelry_type": "ring"},
        ),
    ]

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, spans, debug_meta):
        del product_ids, component_types, spans, debug_meta
        return [seed], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_related(*, seed_cards, semantic_hints, limit):
        del seed_cards, limit
        assert "similar product" in {str(item or "").strip().lower() for item in list(semantic_hints or [])}
        return "seed query text", related

    monkeypatch.setattr(pipeline, "_resolve_products_with_metrics", fake_resolve)
    monkeypatch.setattr(pipeline, "_load_related_product_cards", fake_related)

    state = PipelineWorkflowState()
    state.presentation.canonical_products = []
    state.presentation.selected_components = []
    debug_meta = {"conversation_last_product_ids": [str(seed.product_id)]}
    spans = {"db_product_lookup_ms": 0.0}

    handled = await pipeline._handle_context_related_product_followup(
        state=state,
        detail=SimpleNamespace(attribute_filters={}),
        text="Sure show me the similar product",
        debug_meta=debug_meta,
        spans=spans,
    )

    assert handled is True
    assert state.retrieval.result_count == 2
    assert [str(getattr(card, "attributes", {}).get("master_code", "") or "") for card in state.presentation.canonical_products] == ["REL-1", "REL-2"]
    assert state.presentation.selected_components == [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
    assert debug_meta.get("context_related_product_followup_used") is True


@pytest.mark.asyncio
async def test_component_pipeline_related_product_followup_bypasses_missing_anchor_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)
    seed = _canonical_product(
        sku="SEED-1",
        title="Seed Product",
        attributes={"master_code": "SEED-1", "jewelry_type": "ring"},
    )
    related = _canonical_product(
        sku="REL-1",
        title="Related Product",
        attributes={"master_code": "REL-1", "jewelry_type": "ring"},
    )

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_load_state(*, conversation_id: int):
        del conversation_id
        return conversation_state.load_state({"last_product_ids": [str(seed.product_id)]})

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        del component_types, component_cache, kwargs
        if str(seed.product_id) in {str(item) for item in list(product_ids or [])}:
            return [seed], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}
        return [], {"field_union_size": 0, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_related(*, seed_cards, semantic_hints, limit):
        del seed_cards, semantic_hints, limit
        return "seed query text", [related]

    monkeypatch.setattr(pipeline, "_load_conversation_state", fake_load_state)
    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)
    monkeypatch.setattr(pipeline, "_load_related_product_cards", fake_related)

    decision_state = DecisionState(
        internal_workflow="catalog_search",
        public_workflow="catalog",
        intent_confidence=0.9,
        retrieval_confidence=0.0,
        answerability="none",
        reason="similar product follow-up needs prior product",
        needs_products=True,
        needs_knowledge=False,
        intent="clarify",
        subintent="similar_products",
        user_goal="User wants similar products.",
        response_policy="ask_clarifying_question",
        clarify_question="Which product should I use?",
        pending_task_type="show_similar_products",
        missing_slot="product_anchor",
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Sure show me the similar product", locale="en-US"),
        conversation_id=11,
        run_id="run-related-followup",
        route_decision_override=_workflow_decision(),
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

    assert result.debug.get("context_related_product_followup_used") is True
    assert result.debug.get("catalog_retrieval_blocked_reason") != "llm_requested_product_anchor_clarification"
    assert [card.sku for card in list(result.response.product_carousel or [])] == ["REL-1"]
    assert not any(component.type.value == "clarify" for component in result.response.components)


@pytest.mark.asyncio
async def test_component_pipeline_detail_mode_no_match_has_no_follow_up_quick_replies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _canonical_product(
        sku="LAB-14",
        title="Labret 14g",
        attributes={"master_code": "LAB-14", "jewelry_type": "labret", "gauge": "14g"},
    )

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[str(product.product_id)]), {}

        async def structured_count(self, **kwargs):
            return 1

        async def smart_search(self, **kwargs):
            raise AssertionError("detail no-match should not use semantic fallback")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_parse(*, user_text: str, nlu_data, **_):
        return DetailQuery(
            requested_fields=["stock", "attributes"],
            attribute_filters={"jewelry_type": "labret", "gauge": "1.2mm"},
            wants_image=False,
            is_detail_request=True,
        )

    def fake_detail_resolve(
        self,
        *,
        candidate_cards,
        distance_by_id,
        requested_fields,
        attribute_filters,
        sku_token,
        nlu_product_code,
        max_matches,
        min_confidence,
    ):
        return DetailResolutionResult(
            matches=[],
            match_details=[],
            missing_fields_by_product={},
            requested_fields=requested_fields,
            attribute_filters=attribute_filters,
            has_exact_match=False,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.ProductDetailResolver.resolve_detail_request",
        fake_detail_resolve,
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="Find in-stock labret with 1.2mm gauge", locale="en-US"),
        conversation_id=9,
        run_id="run-detail-no-match",
        route_decision_override=_workflow_decision(),
    )

    assert result.detail_mode_triggered is True
    assert result.response.product_carousel == []
    assert component_contract.follow_up_questions_from_response(result.response) == []
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert result.debug.get("detail_match_count") == 0


@pytest.mark.asyncio
async def test_component_pipeline_detail_mode_broad_price_query_browses_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _canonical_product(
        sku="LAB-14-STEEL",
        title="Labret 14g Steel",
        attributes={"master_code": "LAB-14-STEEL", "jewelry_type": "labret", "gauge": "14g", "material": "steel"},
    )
    second = _canonical_product(
        sku="LAB-16-TI",
        title="Labret 16g Titanium",
        attributes={"master_code": "LAB-16-TI", "jewelry_type": "labret", "gauge": "16g", "material": "titanium"},
    )

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[str(first.product_id), str(second.product_id)]), {}

        async def structured_count(self, **kwargs):
            return 2

        async def smart_search(self, **kwargs):
            raise AssertionError("broad detail browse should not use semantic fallback")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        ordered = []
        for product_id in product_ids:
            if str(product_id) == str(first.product_id):
                ordered.append(first)
            elif str(product_id) == str(second.product_id):
                ordered.append(second)
        return ordered, {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_parse(*, user_text: str, nlu_data, **_):
        return DetailQuery(
            requested_fields=["price"],
            attribute_filters={"jewelry_type": "labret"},
            wants_image=False,
            is_detail_request=True,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="Do you how much for the store of Labret?",
            locale="en-US",
        ),
        conversation_id=9,
        run_id="run-detail-broad-price",
        route_decision_override=_workflow_decision(),
    )

    assert result.detail_mode_triggered is True
    assert len(result.response.product_carousel) == 2
    assert any(component.type.value == "product_cards" for component in result.response.components)
    assert not any(component.type.value == "clarify" for component in result.response.components)
    assert "prices are shown" in result.response.reply_text.lower()
    assert result.debug.get("detail_broad_request_as_catalog") is True
    assert result.debug.get("detail_match_count") == 2


@pytest.mark.asyncio
async def test_component_pipeline_detail_mode_multi_code_request_renders_product_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _canonical_product(
        sku="ULBB3-F01000",
        title="ULBB3",
        attributes={"master_code": "ULBB3", "jewelry_type": "labret", "material": "Titanium G23", "gauge": "16g"},
    )
    second = _canonical_product(
        sku="UTLBB3-F01A07",
        title="UTLBB3",
        attributes={"master_code": "UTLBB3", "jewelry_type": "labret", "material": "Titanium G23", "gauge": "16g"},
    )
    third = _canonical_product(
        sku="DNSM203-A12G44",
        title="DNSM203",
        attributes={"master_code": "DNSM203", "jewelry_type": "labret", "material": "Steel", "gauge": "16g"},
    )
    by_token = {
        "ULBB3": first,
        "UTLBB3": second,
        "DNSM203": third,
    }
    by_id = {str(product.product_id): product for product in by_token.values()}

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            token = str(kwargs.get("sku_token") or "").strip().upper()
            product = by_token.get(token)
            if not product:
                return SimpleNamespace(product_ids=[], cards=[]), {}
            if kwargs.get("return_ids_only"):
                return SimpleNamespace(product_ids=[str(product.product_id)], cards=[]), {}
            return SimpleNamespace(product_ids=[str(product.product_id)], cards=[product]), {}

        async def structured_count(self, **kwargs):
            return 3

        async def smart_search(self, **kwargs):
            raise AssertionError("multi-code detail requests should stay on structured product lookup")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        return [by_id[str(product_id)] for product_id in product_ids if str(product_id) in by_id], {
            "field_union_size": 4,
            "db_round_trips": 0,
            "redis_cache_hits": 0,
        }

    async def fake_parse(*, user_text: str, nlu_data, **_):
        return DetailQuery(
            requested_fields=["attributes"],
            attribute_filters={},
            wants_image=False,
            is_detail_request=True,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="Find me these product ULBB3 UTLBB3 DNSM203",
            locale="en-US",
        ),
        conversation_id=9,
        run_id="run-detail-multi-code",
        route_decision_override=_workflow_decision(),
    )

    component_types = [component.type.value for component in result.response.components]
    assert result.detail_mode_triggered is True
    assert component_types.count("product_cards") == 1
    assert "product_detail" not in component_types
    assert len(result.response.product_carousel) == 3
    assert "product codes you shared below" in result.response.reply_text.lower()
    assert result.debug.get("detail_multi_code_requested") is True
    assert result.debug.get("detail_match_count") == 3


@pytest.mark.asyncio
async def test_component_pipeline_detail_mode_multi_code_request_reports_missing_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _canonical_product(
        sku="ULBB3-F01000",
        title="ULBB3",
        attributes={"master_code": "ULBB3", "jewelry_type": "labret", "material": "Titanium G23", "gauge": "16g"},
    )
    second = _canonical_product(
        sku="DNSM203-A12G44",
        title="DNSM203",
        attributes={"master_code": "DNSM203", "jewelry_type": "labret", "material": "Steel", "gauge": "16g"},
    )
    by_token = {
        "ULBB3": first,
        "DNSM203": second,
    }
    by_id = {str(product.product_id): product for product in by_token.values()}

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            token = str(kwargs.get("sku_token") or "").strip().upper()
            product = by_token.get(token)
            if not product:
                return SimpleNamespace(product_ids=[], cards=[]), {}
            if kwargs.get("return_ids_only"):
                return SimpleNamespace(product_ids=[str(product.product_id)], cards=[]), {}
            return SimpleNamespace(product_ids=[str(product.product_id)], cards=[product]), {}

        async def structured_count(self, **kwargs):
            return 2

        async def smart_search(self, **kwargs):
            raise AssertionError("multi-code detail requests should stay on structured product lookup")

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, component_cache=None, **kwargs):
        return [by_id[str(product_id)] for product_id in product_ids if str(product_id) in by_id], {
            "field_union_size": 4,
            "db_round_trips": 0,
            "redis_cache_hits": 0,
        }

    async def fake_parse(*, user_text: str, nlu_data, **_):
        return DetailQuery(
            requested_fields=["attributes"],
            attribute_filters={},
            wants_image=False,
            is_detail_request=True,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse_async",
        fake_parse,
    )

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="Find me these product ULBB3 UTLBB3 DNSM203",
            locale="en-US",
        ),
        conversation_id=9,
        run_id="run-detail-multi-code-missing",
        route_decision_override=_workflow_decision(),
    )

    assert len(result.response.product_carousel) == 2
    assert "i found 2 of the 3 product codes you shared below" in result.response.reply_text.lower()
    assert "i couldn't find: utlbb3" in result.response.reply_text.lower()
    assert result.debug.get("detail_multi_code_missing_tokens") == ["UTLBB3"]
