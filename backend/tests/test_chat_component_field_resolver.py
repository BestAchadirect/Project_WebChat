from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.product import Product, StockStatus
from app.services.chat.components.field_resolver import FieldDependencyResolver
from app.services.chat.components.types import ComponentType


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


@pytest.mark.asyncio
async def test_field_resolver_skips_enrichment_when_base_fields_are_sufficient() -> None:
    product = _make_product(with_attrs=True)
    fake_db = _FakeDB(products=[product], enrich_rows=[])
    resolver = FieldDependencyResolver(db=fake_db)  # type: ignore[arg-type]

    canonical, meta = await resolver.resolve(
        product_ids=[product.id],
        component_types=[ComponentType.PRODUCT_TABLE],
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
        component_types=[ComponentType.COMPARE],
        redis_cache=None,
    )

    assert len(canonical) == 1
    assert canonical[0].material == "Titanium"
    assert canonical[0].gauge == "14g"
    assert canonical[0].attributes.get("color") == "Black"
    assert meta["enrichment_used"] is True
    assert meta["db_round_trips"] == 2
