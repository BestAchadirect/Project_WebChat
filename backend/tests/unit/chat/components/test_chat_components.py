from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.product import Product, StockStatus
from app.schemas.chat import KnowledgeSource
from app.services.ai.llm_service import llm_service
from app.services.chat.components.builders.clarify import ClarifyComponent
from app.services.chat.components.builders.error import ErrorComponent
from app.services.chat.components.builders.knowledge_answer import KnowledgeAnswerComponent
from app.services.chat.components.builders.product_cards import ProductCardsComponent
from app.services.chat.components.builders.product_detail import ProductDetailComponent
from app.services.chat.components.builders.query_summary import QuerySummaryComponent
from app.services.chat.components.cache import ComponentCache, stable_cache_key
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.field_resolver import FieldDependencyResolver
from app.services.chat.components.registry import ComponentRegistry
from app.services.chat.components.types import ComponentSource, ComponentType


class _ScalarWrapper:
    def __init__(self, values):
        self._values = list(values)

    def all(self):
        return list(self._values)


class _Result:
    def __init__(self, *, scalars=None, rows=None):
        self._scalars = list(scalars or [])
        self._rows = list(rows or [])

    def scalars(self):
        return _ScalarWrapper(self._scalars)

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, *, products=None, enrich_rows=None):
        self._products = list(products or [])
        self._enrich_rows = list(enrich_rows or [])
        self.execute_calls = 0

    async def execute(self, stmt):
        self.execute_calls += 1
        if self.execute_calls == 1:
            return _Result(scalars=self._products)
        return _Result(rows=self._enrich_rows)


def _make_product(*, with_attrs: bool) -> Product:
    attrs = {"material": "Steel", "gauge": "16g"} if with_attrs else {}
    return Product(
        id=uuid4(),
        sku="SKU-1",
        master_code="Ring",
        group_id=uuid4(),
        price=10.0,
        currency="USD",
        stock_status=StockStatus.in_stock,
        stock_qty=4,
        image_url="https://example.com/a.jpg",
        product_url="https://example.com/p1",
        attributes=attrs,
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


def _sample_products() -> list[CanonicalProduct]:
    return [
        CanonicalProduct(
            product_id=uuid4(),
            sku="SKU-1",
            title="Ring One",
            price=Decimal("12.50"),
            currency="USD",
            in_stock=True,
            stock_qty=5,
            material="Steel",
            gauge="16g",
            image_url="https://example.com/1.jpg",
            attributes={"material": "Steel", "gauge": "16g"},
            product_url="https://example.com/p1",
        ),
        CanonicalProduct(
            product_id=uuid4(),
            sku="SKU-2",
            title="Ring Two",
            price=Decimal("20.00"),
            currency="USD",
            in_stock=False,
            stock_qty=0,
            material="Titanium",
            gauge="14g",
            image_url="https://example.com/2.jpg",
            attributes={"material": "Titanium", "gauge": "14g"},
            product_url="https://example.com/p2",
        ),
    ]


def _sample_context() -> ComponentContext:
    products = _sample_products()
    return ComponentContext(
        user_text="show ring products",
        locale="en-US",
        workflow="catalog",
        query_summary="show products",
        source=ComponentSource.SQL,
        selected_components=[ComponentType.QUERY_SUMMARY],
        canonical_products=products,
        knowledge_sources=[
            KnowledgeSource(
                source_id="kb-1",
                title="Shipping",
                content_snippet="Ships in 3-5 days",
                relevance=0.9,
            )
        ],
        knowledge_answer="Shipping takes 3-5 days.",
        result_count=len(products),
        ambiguity_reason="need_more_context",
        error_message="component error",
    )


def test_registry_maps_all_component_types() -> None:
    for component_type in ComponentType:
        builder = ComponentRegistry.builder_for(component_type)
        assert builder.component_type == component_type


def test_registry_missing_builder_raises_controlled_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ComponentRegistry, "_registry", {})
    with pytest.raises(KeyError):
        ComponentRegistry.builder_for(ComponentType.PRODUCT_CARDS)


@pytest.mark.asyncio
async def test_field_resolver_skips_enrichment_when_base_fields_are_sufficient() -> None:
    product = _make_product(with_attrs=True)
    fake_db = _FakeDB(products=[product], enrich_rows=[])
    resolver = FieldDependencyResolver(db=fake_db)  # type: ignore[arg-type]

    canonical, meta = await resolver.resolve(
        product_ids=[product.id],
        component_types=[ComponentType.PRODUCT_CARDS],
        redis_cache=None,
    )

    assert len(canonical) == 1
    assert canonical[0].material == "Steel"
    assert canonical[0].gauge == "16g"
    assert canonical[0].price == Decimal("10.0")
    assert meta["enrichment_used"] is False
    assert meta["db_round_trips"] == 1
    assert meta["field_union_size"] >= 1


@pytest.mark.asyncio
async def test_field_resolver_runs_single_enrichment_query_for_full_specs() -> None:
    product = _make_product(with_attrs=False)
    enrich_rows = [
        SimpleNamespace(product_id=product.id, name="material", value="Titanium"),
        SimpleNamespace(product_id=product.id, name="gauge", value="14g"),
        SimpleNamespace(product_id=product.id, name="color", value="Black"),
    ]
    fake_db = _FakeDB(products=[product], enrich_rows=enrich_rows)
    resolver = FieldDependencyResolver(db=fake_db)  # type: ignore[arg-type]

    canonical, meta = await resolver.resolve(
        product_ids=[product.id],
        component_types=[ComponentType.PRODUCT_CARDS],
        redis_cache=None,
    )

    assert len(canonical) == 1
    assert canonical[0].material == "Titanium"
    assert canonical[0].gauge == "14g"
    assert canonical[0].attributes.get("color") == "Black"
    assert meta["enrichment_used"] is True
    assert meta["db_round_trips"] == 2


@pytest.mark.asyncio
async def test_component_cache_roundtrip() -> None:
    cache = ComponentCache()

    assert await cache.get_json("key") is None
    await cache.set_json("key", {"v": 1}, ttl_seconds=30)
    assert await cache.get_json("key") == {"v": 1}


def test_stable_cache_key_is_deterministic() -> None:
    key_a = stable_cache_key("prefix", {"b": 2, "a": 1})
    key_b = stable_cache_key("prefix", {"a": 1, "b": 2})
    assert key_a == key_b


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder_cls, expected_type, expected_key",
    [
        (QuerySummaryComponent, ComponentType.QUERY_SUMMARY, "text"),
        (ProductCardsComponent, ComponentType.PRODUCT_CARDS, "cards"),
        (ProductDetailComponent, ComponentType.PRODUCT_DETAIL, "product"),
        (ClarifyComponent, ComponentType.CLARIFY, "message"),
        (KnowledgeAnswerComponent, ComponentType.KNOWLEDGE_ANSWER, "answer"),
        (ErrorComponent, ComponentType.ERROR, "message"),
    ],
)
async def test_builder_outputs_shape(builder_cls, expected_type: ComponentType, expected_key: str) -> None:
    context = _sample_context()
    component = await builder_cls().build(context)
    assert str(component.type.value) == expected_type.value
    assert expected_key in component.data
    if expected_key == "cards":
        assert component.data["cards"][0]["master_code"] == "Ring One"
    elif expected_key == "product":
        assert component.data["product"]["master_code"] == "Ring One"


@pytest.mark.asyncio
async def test_clarify_builder_hides_questions_and_suggestions_from_public_payload() -> None:
    context = _sample_context()
    context.ambiguity_reason = "knowledge_needs_clarification"
    context.debug = {
        "clarify_message": "I want to give you the right answer, but I need one more detail.",
        "clarify_questions": [
            "Which policy or contact detail do you need?",
            "Is this for sales or support?",
        ],
        "clarify_suggestions": [
            "How can I contact you?",
            "What is your shipping policy?",
            "What is your refund policy?",
            "extra item should be trimmed",
        ],
    }

    component = await ClarifyComponent().build(context)

    assert component.data["message"] == "I want to give you the right answer, but I need one more detail."
    assert "questions" not in component.data
    assert "suggestions" not in component.data


@pytest.mark.asyncio
async def test_clarify_builder_can_use_contextual_llm_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _sample_context()
    context.ambiguity_reason = "need_more_context"
    context.error_message = None
    context.debug = {}

    async def fake_generate_chat_json(**kwargs):
        return {"message": "Which size are you looking for?"}

    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    component = await ClarifyComponent().build(context)

    assert component.data["message"] == "Which size are you looking for?"


@pytest.mark.asyncio
async def test_error_builder_can_use_contextual_llm_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _sample_context()
    context.error_message = None

    async def fake_generate_chat_json(**kwargs):
        return {"message": "I ran into an issue with that request. Please try again in a moment."}

    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    component = await ErrorComponent().build(context)

    assert component.data["message"] == "I ran into an issue with that request. Please try again in a moment."


@pytest.mark.asyncio
async def test_contextual_component_copy_falls_back_to_tone_variants_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _sample_context()
    context.error_message = None
    context.debug = {}

    async def broken_generate_chat_json(**kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", broken_generate_chat_json)

    clarify_component = await ClarifyComponent().build(context)
    error_component = await ErrorComponent().build(context)

    assert clarify_component.data["message"]
    assert error_component.data["message"]
