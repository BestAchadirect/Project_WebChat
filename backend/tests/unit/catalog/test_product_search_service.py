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
    master_code: str = ""
    group_id: object | None = None
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
        name=product.master_code or product.sku,
        description=None,
        price=1.0,
        currency="USD",
        stock_status=product.stock_status,
        image_url=None,
        product_url=None,
        attributes={"master_code": product.master_code or product.sku, "material": "steel", "jewelry_type": "barbell"},
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
async def test_structured_search_uses_master_code_lookup_for_group(monkeypatch: pytest.MonkeyPatch) -> None:
    group_id = uuid4()
    anchor = _ProductStub(id=uuid4(), sku="BLK466-F02A12", master_code="BLK466", group_id=group_id)
    second = _ProductStub(id=uuid4(), sku="BLK466-F04A12", master_code="BLK466", group_id=group_id)
    db = _QueueDB(
        [
            _FakeResult(rows=[]),
            _FakeResult(scalar=anchor),
            _FakeResult(rows=[anchor, second]),
        ]
    )
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
        sku_token="BLK466",
        attribute_filters={},
        limit=5,
    )

    assert result.product_ids == [anchor.id, second.id]
    assert [card.sku for card in result.cards] == ["BLK466-F02A12", "BLK466-F04A12"]
    assert meta["structured_used_sku"] is True
    assert meta["structured_used_master_code"] is True


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
async def test_structured_search_treats_category_as_multi_tag_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _ProductStub(id=uuid4(), sku="BNCHK-A07000")
    db = _QueueDB([_FakeResult(rows=[(product.id,)]), _FakeResult(rows=[product])])
    service = CatalogProductSearchService(db=db)

    async def fake_cards_from_products(self, products):
        return [_card(item) for item in products]

    async def fake_definitions_by_name(*args, **kwargs):
        return {"category": SimpleNamespace(id=10, is_multivalue=True)}

    monkeypatch.setattr(eav_service, "get_definitions_by_name", fake_definitions_by_name)
    monkeypatch.setattr(eav_service, "get_product_attributes", lambda *args, **kwargs: {})
    monkeypatch.setattr(service, "_cards_from_products", fake_cards_from_products.__get__(service))

    result, meta = await service.structured_search(
        sku_token=None,
        attribute_filters={"category": ["Belly Bananas", "Checkers"]},
        limit=5,
    )

    assert result.product_ids == [product.id]
    assert result.cards[0].sku == "BNCHK-A07000"
    assert meta["structured_filter_count"] == 1
    assert len(db.executed) == 2


@pytest.mark.asyncio
async def test_structured_search_material_lookup_uses_explicit_attributes_without_projection_fallback(
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


@pytest.mark.asyncio
async def test_vector_search_pushes_hard_filters_into_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _QueueDB([_FakeResult(rows=[])])
    service = CatalogProductSearchService(db=db)

    async def fake_definitions_by_name(*args, **kwargs):
        return {"material": SimpleNamespace(id=10)}

    monkeypatch.setattr(eav_service, "get_definitions_by_name", fake_definitions_by_name)

    result = await service.vector_search(
        query_embedding=[0.1, 0.2],
        limit=5,
        attribute_filters={"material": "steel"},
    )

    assert result.cards == []
    assert service.last_meta["retrieval_filter_pushdown_keys"] == ["material"]
    assert service.last_meta["retrieval_filter_pushdown_slot_count"] == 1
    sql_text = str(db.executed[0]).lower()
    assert "exists" in sql_text
    assert "product_attribute_values.attribute_id" in sql_text


@pytest.mark.asyncio
async def test_lexical_search_pushes_direct_filters_into_sql() -> None:
    db = _QueueDB([_FakeResult(rows=[])])
    service = CatalogProductSearchService(db=db)

    result = await service.lexical_search(
        query_text="x",
        limit=5,
        attribute_filters={"max_price": "50", "stock_status": "in_stock"},
    )

    assert result.cards == []
    assert service.last_meta["retrieval_filter_pushdown_keys"] == ["max_price", "stock_status"]
    assert service.last_meta["retrieval_filter_pushdown_direct_count"] == 2
    sql_text = str(db.executed[0]).lower()
    assert "products.price <=" in sql_text
    assert "products.stock_status" in sql_text


def test_catalog_eav_partial_match_keys_use_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CATALOG_EAV_PARTIAL_MATCH_KEYS", "material,finish")

    assert catalog_eav_partial_match_keys() == frozenset({"material", "finish"})
    assert uses_eav_partial_match("material") is True
    assert uses_eav_partial_match("threading") is False


def test_catalog_eav_partial_match_keys_default_includes_new_facets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CATALOG_EAV_PARTIAL_MATCH_KEYS", "")

    keys = catalog_eav_partial_match_keys()

    assert {"body_part", "feature", "presentation_type", "theme"}.issubset(keys)


def test_product_search_normalizes_legacy_attribute_keys_to_db_names() -> None:
    clean = CatalogProductSearchService._normalize_filter_map(
        {
            "body_part": "nose",
            "body part": "ear",
            "diameter": "8mm",
            "type": "labret",
        }
    )

    assert clean["body_location"] == "ear"
    assert clean["outer_diameter"] == "8mm"
    assert clean["jewelry_type"] == "labret"
    assert "body_part" not in clean
    assert "diameter" not in clean


def test_product_search_normalizes_category_arrays_as_tag_memberships() -> None:
    clean = CatalogProductSearchService._normalize_filter_map(
        {
            "category": ["Belly Bananas", "Checkers", "Belly Bananas"],
        }
    )

    assert clean == {"category": "belly bananas;;checkers"}
