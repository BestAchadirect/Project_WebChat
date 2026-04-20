from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")
pytest.importorskip("sqlalchemy")

from app.core.config import settings
from app.schemas.chat import ProductCard
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.catalog.search_policy import catalog_eav_partial_match_keys, uses_eav_partial_match
from app.services.catalog.attributes_service import eav_service


@dataclass
class _ProductStub:
    id: object
    sku: str
    search_text: str = ""
    is_active: bool = True
    stock_status: str = "in_stock"
    created_at: datetime = datetime.now(timezone.utc)


class _FakeResult:
    def __init__(self, *, rows=None, scalar=None):
        self._rows = list(rows or [])
        self._scalar = scalar

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def first(self):
        return self._rows[0] if self._rows else None


class _QueueDB:
    def __init__(self, results):
        self.results = list(results)
        self.executed = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        if not self.results:
            raise AssertionError("Unexpected execute call")
        return self.results.pop(0)


def _card(product: _ProductStub) -> ProductCard:
    return ProductCard(
        id=product.id,
        object_id=product.sku,
        sku=product.sku,
        legacy_sku=[],
        name=product.sku,
        description=None,
        price=1.0,
        currency="USD",
        stock_status=product.stock_status,
        image_url=None,
        product_url=None,
        attributes={"material": "steel", "jewelry_type": "barbell"},
    )


@pytest.mark.asyncio
async def test_structured_search_uses_sku_lookup_without_projection_read(monkeypatch: pytest.MonkeyPatch) -> None:
    product = _ProductStub(id=uuid4(), sku="SKU-1")
    db = _QueueDB([_FakeResult(rows=[product])])
    service = CatalogProductSearchService(db=db)

    async def fake_cards_from_products(self, products):
        return [_card(item) for item in products]

    monkeypatch.setattr(
        eav_service,
        "get_product_attributes",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(service, "_cards_from_products", fake_cards_from_products.__get__(service))

    result, meta = await service.structured_search(
        sku_token=" SKU-1 ",
        attribute_filters={},
        limit=5,
    )

    assert result.product_ids == [product.id]
    assert len(result.cards) == 1
    assert result.cards[0].sku == "SKU-1"
    assert meta["structured_used_sku"] is True
    assert len(db.executed) == 1


@pytest.mark.asyncio
async def test_structured_search_uses_eav_filters_for_single_and_multi_filter_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _ProductStub(id=uuid4(), sku="MAT-1")
    db = _QueueDB(
        [
            _FakeResult(rows=[(product.id,)]),
            _FakeResult(rows=[product]),
            _FakeResult(rows=[(product.id,)]),
            _FakeResult(rows=[product]),
        ]
    )
    service = CatalogProductSearchService(db=db)

    async def fake_cards_from_products(self, products):
        return [_card(item) for item in products]

    async def fake_definitions_by_name(*args, **kwargs):
        names = list(args[1] if len(args) > 1 else kwargs.get("names", []) or [])
        return {name: SimpleNamespace(id=index + 10) for index, name in enumerate(names)}

    monkeypatch.setattr(
        eav_service,
        "get_definitions_by_name",
        fake_definitions_by_name,
    )
    monkeypatch.setattr(
        eav_service,
        "get_product_attributes",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(service, "_cards_from_products", fake_cards_from_products.__get__(service))

    single_result, single_meta = await service.structured_search(
        sku_token=None,
        attribute_filters={"material": "steel"},
        limit=5,
    )
    multi_result, multi_meta = await service.structured_search(
        sku_token=None,
        attribute_filters={"material": "steel", "jewelry_type": "barbell"},
        limit=5,
    )

    assert single_result.product_ids == [product.id]
    assert single_meta["structured_filter_count"] == 1
    assert multi_result.product_ids == [product.id]
    assert multi_meta["structured_filter_count"] == 2
    assert single_meta["structured_used_sku"] is False
    assert multi_meta["structured_used_sku"] is False


@pytest.mark.asyncio
async def test_structured_search_material_fallback_still_works_without_projection_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _ProductStub(id=uuid4(), sku="MAT-2", search_text="implant grade titanium")
    db = _QueueDB(
        [
            _FakeResult(rows=[]),
            _FakeResult(rows=[(product.id,)]),
            _FakeResult(rows=[product]),
        ]
    )
    service = CatalogProductSearchService(db=db)

    async def fake_cards_from_products(self, products):
        return [_card(item) for item in products]

    async def fake_definitions_by_name(*args, **kwargs):
        return {"material": SimpleNamespace(id=10)}

    monkeypatch.setattr(
        eav_service,
        "get_definitions_by_name",
        fake_definitions_by_name,
    )
    monkeypatch.setattr(
        eav_service,
        "get_product_attributes",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(service, "_cards_from_products", fake_cards_from_products.__get__(service))

    result, meta = await service.structured_search(
        sku_token=None,
        attribute_filters={"material": "implant grade titanium"},
        limit=5,
    )

    assert result.product_ids == [product.id]
    assert result.cards[0].sku == "MAT-2"
    assert meta["structured_filter_count"] == 1


@pytest.mark.asyncio
async def test_structured_count_uses_eav_only(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _QueueDB([_FakeResult(scalar=1)])
    service = CatalogProductSearchService(db=db)

    count = await service.structured_count(
        sku_token="SKU-1",
        attribute_filters={},
    )

    assert count == 1
    assert len(db.executed) == 1


def test_catalog_eav_partial_match_keys_use_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CATALOG_EAV_PARTIAL_MATCH_KEYS", "material,finish")

    assert catalog_eav_partial_match_keys() == frozenset({"material", "finish"})
    assert uses_eav_partial_match("material") is True
    assert uses_eav_partial_match("threading") is False


def test_catalog_eav_partial_match_keys_default_includes_new_facets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CATALOG_EAV_PARTIAL_MATCH_KEYS", "")

    keys = catalog_eav_partial_match_keys()

    assert {"body_part", "feature", "presentation_type", "theme"}.issubset(keys)
