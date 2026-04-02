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
from app.services.chat.components.types import ComponentSource
from app.services.chat.parsing.detail_query_parser import DetailQuery
from app.services.chat.retrieval.product_detail_resolver import DetailResolutionResult
from app.services.chat.presentation import component_contract


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

    def fake_parse(*, user_text: str, nlu_data, **_):
        return DetailQuery(
            requested_fields=["price", "stock"],
            attribute_filters={"jewelry_type": "barbell", "color": "black", "gauge": "25mm"},
            wants_image=False,
            is_detail_request=True,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse",
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

    def fake_parse(*, user_text: str, nlu_data, **_):
        return DetailQuery(
            requested_fields=["image"],
            attribute_filters={"jewelry_type": "labret"},
            wants_image=True,
            is_detail_request=True,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse",
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

    def fake_parse(*, user_text: str, nlu_data, **_):
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
        "app.services.chat.components.pipeline.DetailQueryParser.parse",
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
    assert component_contract.follow_up_questions_from_response(result.response)
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert "couldn't find a product" in result.response.reply_text.lower()
    assert result.debug.get("detail_match_count") == 0


@pytest.mark.asyncio
async def test_component_pipeline_detail_mode_broad_price_query_requests_clarification(
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
            raise AssertionError("broad detail clarification should not use semantic fallback")

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

    def fake_parse(*, user_text: str, nlu_data, **_):
        return DetailQuery(
            requested_fields=["price"],
            attribute_filters={"jewelry_type": "labret"},
            wants_image=False,
            is_detail_request=True,
        )

    pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.services.chat.components.pipeline.DetailQueryParser.parse",
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
    assert result.response.product_carousel == []
    assert any(component.type.value == "clarify" for component in result.response.components)
    assert "not sure which labret" in result.response.reply_text.lower()
    assert "share a sku" in result.response.reply_text.lower()
    assert result.debug.get("detail_match_count") == 2
