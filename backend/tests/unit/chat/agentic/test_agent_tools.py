import pytest
from pydantic import ValidationError
from types import SimpleNamespace

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")
pytestmark = pytest.mark.agentic

from app.schemas.chat import KnowledgeSource, ProductCard
from app.services.ai.llm_service import llm_service
from app.services.chat.agentic.tool_registry import (
    CheckInventoryArgs,
    GetProductDetailsArgs,
    SearchKnowledgeBaseArgs,
    SearchProductFilters,
    SearchProductsArgs,
    AgentToolRegistry,
)
from app.services.chat.agentic.tool_handlers import paginate_items, product_card_matches_filters


def test_search_products_args_accepts_page_size_alias() -> None:
    args = SearchProductsArgs.model_validate(
        {
            "query": "Titanium ring",
            "page": 2,
            "pageSize": 5,
            "filters": {"material": "Titanium", "min_price": "10"},
        }
    )
    assert args.page == 2
    assert args.page_size == 5
    assert args.filters is not None
    assert args.filters.material == "Titanium"
    assert args.filters.min_price == 10.0


def test_search_products_args_rejects_unsupported_filter() -> None:
    try:
        SearchProductsArgs.model_validate(
            {
                "query": "Ring",
                "filters": {"brand": "X"},
            }
        )
    except ValidationError as exc:
        assert "Extra inputs are not permitted" in str(exc)
        return
    raise AssertionError("Expected ValidationError")


def test_search_products_args_rejects_invalid_price_range() -> None:
    try:
        SearchProductsArgs.model_validate(
            {
                "query": "Ring",
                "filters": {"min_price": 50, "max_price": 10},
            }
        )
    except ValidationError as exc:
        assert "min_price cannot be greater than max_price" in str(exc)
        return
    raise AssertionError("Expected ValidationError")


def test_search_product_filters_to_filter_map_omits_none_values() -> None:
    filters = SearchProductFilters.model_validate(
        {
            "material": "Titanium",
            "theme": "  celestial  ",
        }
    )

    assert filters.to_filter_map() == {
        "material": "Titanium",
        "theme": "celestial",
    }


def test_product_card_matches_filters_uses_fuzzy_attribute_matching() -> None:
    card = ProductCard(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        sku="BLACK-OPAL-LABRET",
        legacy_sku=[],
        name="Black Opal Labret",
        price=14.0,
        currency="USD",
        stock_status="in_stock",
        attributes={
            "category": "Body Jewelry;;Labrets",
            "jewelry_type": "Labret",
            "color": "Black Opal",
            "material": "Titanium",
        },
    )

    assert product_card_matches_filters(card, {"category": "labrets", "color": "black"})
    assert not product_card_matches_filters(card, {"material": "opal"})


def test_get_product_details_args_validates_empty_sku() -> None:
    try:
        GetProductDetailsArgs.model_validate({"sku": "   "})
    except ValidationError as exc:
        assert "sku cannot be empty" in str(exc)
        return
    raise AssertionError("Expected ValidationError")


def test_search_knowledge_base_limit_range() -> None:
    try:
        SearchKnowledgeBaseArgs.model_validate({"query": "shipping", "limit": 99})
    except ValidationError as exc:
        assert "less than or equal to 5" in str(exc)
        return
    raise AssertionError("Expected ValidationError")


def test_normalize_tool_result_exposes_renderable_products_and_sources() -> None:
    normalized_products = AgentToolRegistry.normalize_tool_result(
        tool_name="get_product_details",
        result={
            "tool": "get_product_details",
            "status": "ambiguous",
            "candidates": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "sku": "LAB-14",
                    "legacy_sku": [],
                    "name": "LAB-14",
                    "price": 10.0,
                    "currency": "USD",
                    "stock_status": "in_stock",
                    "attributes": {"material": "Titanium"},
                }
            ],
        },
    )
    normalized_sources = AgentToolRegistry.normalize_tool_result(
        tool_name="search_knowledge_base",
        result={
            "tool": "search_knowledge_base",
            "status": "ok",
            "items": [
                {
                    "source_id": "src-1",
                    "title": "Shipping Policy",
                    "snippet": "Shipping details",
                    "category": "Policy",
                    "relevance": 0.91,
                }
            ],
        },
    )

    assert normalized_products.result_count == 1
    assert normalized_products.tool_name == "get_product_details"
    assert len(normalized_products.products) == 1
    assert isinstance(normalized_products.products[0], ProductCard)
    assert normalized_products.sources == []
    assert normalized_sources.result_count == 1
    assert normalized_sources.tool_name == "search_knowledge_base"
    assert normalized_sources.products == []
    assert len(normalized_sources.sources) == 1
    assert isinstance(normalized_sources.sources[0], KnowledgeSource)
    assert normalized_sources.sources[0].content_snippet == "Shipping details"


def test_normalize_tool_result_skips_invalid_artifacts_without_losing_result_count() -> None:
    normalized = AgentToolRegistry.normalize_tool_result(
        tool_name="search_products",
        result={
            "tool": "search_products",
            "status": "ok",
            "items": [
                {
                    "id": "55555555-5555-5555-5555-555555555555",
                    "sku": "OK-1",
                    "legacy_sku": [],
                    "name": "Valid Product",
                    "price": 15.0,
                    "currency": "USD",
                    "stock_status": "in_stock",
                    "attributes": {},
                },
                {"sku": "BROKEN"},
            ],
            "totalItems": 2,
        },
    )

    assert normalized.result_count == 2
    assert [card.sku for card in normalized.products] == ["OK-1"]


def test_paginate_items_clamps_page_size_to_max_items() -> None:
    items = list(range(15))
    page_items, total_items, safe_page, total_pages = paginate_items(
        items,
        page=2,
        page_size=20,
        max_items=10,
    )

    assert total_items == 15
    assert safe_page == 2
    assert total_pages == 2
    assert page_items == list(range(10, 15))


@pytest.mark.asyncio
async def test_get_product_details_returns_ambiguous_candidates() -> None:
    registry = AgentToolRegistry(db=object())

    async def fake_resolve(reference: str, *, max_candidates: int = 5):
        return {
            "status": "ambiguous",
            "matched_by": "normalized_reference",
            "candidates": [
                ProductCard(
                    id="11111111-1111-1111-1111-111111111111",
                    sku="LAB-14",
                    legacy_sku=[],
                    name="LAB-14",
                    price=10.0,
                    currency="USD",
                    stock_status="in_stock",
                    attributes={"material": "Titanium"},
                ),
                ProductCard(
                    id="22222222-2222-2222-2222-222222222222",
                    sku="LAB-14-ALT",
                    legacy_sku=[],
                    name="LAB-14",
                    price=12.0,
                    currency="USD",
                    stock_status="out_of_stock",
                    attributes={"material": "Steel"},
                ),
            ],
        }

    registry._catalog_search.resolve_product_reference = fake_resolve  # type: ignore[attr-defined]

    payload = await registry.get_product_details(GetProductDetailsArgs(sku="lab 14"))

    assert payload["tool"] == "get_product_details"
    assert payload["status"] == "ambiguous"
    assert payload["source"] == "catalog_db"
    assert payload["found"] is False
    assert payload["ambiguous"] is True
    assert payload["matched_by"] == "normalized_reference"
    assert len(payload["candidates"]) == 2
    assert payload["candidates"][0]["sku"] == "LAB-14"
    assert payload["candidates"][0]["price"] == 10.0
    assert payload["candidates"][0]["currency"] == "USD"


@pytest.mark.asyncio
async def test_get_product_details_returns_normalized_not_found_shape() -> None:
    registry = AgentToolRegistry(db=object())

    async def fake_resolve(reference: str, *, max_candidates: int = 5):
        return {
            "status": "not_found",
            "matched_by": "",
            "product": None,
        }

    registry._catalog_search.resolve_product_reference = fake_resolve  # type: ignore[attr-defined]

    payload = await registry.get_product_details(GetProductDetailsArgs(sku="UNKNOWN-1"))

    assert payload["tool"] == "get_product_details"
    assert payload["status"] == "not_found"
    assert payload["source"] == "catalog_db"
    assert payload["found"] is False
    assert payload["ambiguous"] is False
    assert payload["sku"] == "UNKNOWN-1"
    assert payload["matched_by"] == ""
    assert payload["candidates"] == []


@pytest.mark.asyncio
async def test_check_inventory_db_uses_resolved_reference_when_exact_sku_misses() -> None:
    registry = AgentToolRegistry(db=object())
    resolved_card = ProductCard(
        id="33333333-3333-3333-3333-333333333333",
        sku="LAB-14",
        legacy_sku=[],
        name="LAB-14",
        price=10.0,
        currency="USD",
        stock_status="in_stock",
        attributes={"material": "Titanium"},
    )

    async def fake_snapshot(sku: str):
        if sku == "lab 14":
            return {"found": False, "sku": sku, "source": "db"}
        return {"found": True, "sku": sku, "stock_status": "in_stock", "source": "db"}

    async def fake_resolve(reference: str, *, max_candidates: int = 5):
        return {
            "status": "resolved",
            "matched_by": "normalized_reference",
            "product": resolved_card,
        }

    registry._catalog_search.get_inventory_snapshot = fake_snapshot  # type: ignore[attr-defined]
    registry._catalog_search.resolve_product_reference = fake_resolve  # type: ignore[attr-defined]

    payload = await registry.check_inventory_db(CheckInventoryArgs(sku="lab 14"))

    assert payload["tool"] == "check_inventory_db"
    assert payload["status"] == "ok"
    assert payload["found"] is True
    assert payload["sku"] == "LAB-14"
    assert payload["matched_by"] == "normalized_reference"
    assert payload["requested_sku"] == "lab 14"
    assert payload["ambiguous"] is False
    assert payload["candidates"] == []


@pytest.mark.asyncio
async def test_search_products_returns_normalized_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AgentToolRegistry(db=object())

    async def fake_embedding(query: str):
        return [0.1, 0.2]

    async def fake_vector_search(**kwargs):
        return SimpleNamespace(
            cards=[
                ProductCard(
                    id="44444444-4444-4444-4444-444444444444",
                    sku="TI-1",
                    legacy_sku=[],
                    name="Titanium Labret",
                    price=19.0,
                    currency="USD",
                    stock_status="in_stock",
                    attributes={"material": "Titanium"},
                )
            ]
        )

    monkeypatch.setattr(llm_service, "generate_embedding", fake_embedding)
    registry._catalog_search.vector_search = fake_vector_search  # type: ignore[attr-defined]

    payload = await registry.search_products(
        SearchProductsArgs.model_validate(
            {
                "query": "titanium labret",
                "filters": {"material": "Titanium"},
                "page": 1,
                "pageSize": 5,
            }
        )
    )

    assert payload["tool"] == "search_products"
    assert payload["status"] == "ok"
    assert payload["source"] == "catalog_db"
    assert payload["query"] == "titanium labret"
    assert payload["filters"] == {"material": "titanium"}
    assert payload["totalItems"] == 1
    assert payload["items"][0]["sku"] == "TI-1"


@pytest.mark.asyncio
async def test_search_products_uses_lexical_rescue_when_vector_filters_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AgentToolRegistry(db=object())

    async def fake_embedding(query: str):
        return [0.1, 0.2]

    async def fake_vector_search(**kwargs):
        return SimpleNamespace(
            cards=[
                ProductCard(
                    id="44444444-4444-4444-4444-444444444444",
                    sku="NOPE-1",
                    legacy_sku=[],
                    name="Plain Ring",
                    price=19.0,
                    currency="USD",
                    stock_status="in_stock",
                    attributes={"jewelry_type": "Ring", "color": "Silver"},
                )
            ]
        )

    async def fake_lexical_search(**kwargs):
        return SimpleNamespace(
            cards=[
                ProductCard(
                    id="55555555-5555-5555-5555-555555555555",
                    sku="BOLAB-1",
                    legacy_sku=[],
                    name="Black Opal Labret",
                    price=14.0,
                    currency="USD",
                    stock_status="in_stock",
                    attributes={
                        "category": "Body Jewelry;;Labrets",
                        "jewelry_type": "Labret",
                        "color": "Black Opal",
                    },
                )
            ]
        )

    async def fake_structured_search(**kwargs):
        return SimpleNamespace(cards=[]), {}

    monkeypatch.setattr(llm_service, "generate_embedding", fake_embedding)
    registry._catalog_search.vector_search = fake_vector_search  # type: ignore[attr-defined]
    registry._catalog_search.lexical_search = fake_lexical_search  # type: ignore[attr-defined]
    registry._catalog_search.structured_search = fake_structured_search  # type: ignore[attr-defined]

    payload = await registry.search_products(
        SearchProductsArgs.model_validate(
            {
                "query": "labrets black opal",
                "filters": {"category": "labrets", "color": "black"},
                "page": 1,
                "pageSize": 5,
            }
        )
    )

    assert payload["status"] == "ok"
    assert payload["retrievalMode"] == "lexical_rescue"
    assert payload["totalItems"] == 1
    assert payload["items"][0]["sku"] == "BOLAB-1"


@pytest.mark.asyncio
async def test_search_products_returns_normalized_empty_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AgentToolRegistry(db=object())

    async def fake_embedding(query: str):
        return [0.1, 0.2]

    async def fake_vector_search(**kwargs):
        return SimpleNamespace(cards=[])

    monkeypatch.setattr(llm_service, "generate_embedding", fake_embedding)
    registry._catalog_search.vector_search = fake_vector_search  # type: ignore[attr-defined]

    payload = await registry.search_products(
        SearchProductsArgs.model_validate(
            {
                "query": "titanium labret",
                "filters": {"material": "Titanium"},
                "page": 2,
                "pageSize": 5,
            }
        )
    )

    assert payload["tool"] == "search_products"
    assert payload["status"] == "empty"
    assert payload["source"] == "catalog_db"
    assert payload["query"] == "titanium labret"
    assert payload["filters"] == {"material": "titanium"}
    assert payload["items"] == []
    assert payload["totalItems"] == 0
    assert payload["page"] == 2
    assert payload["pageSize"] == 5
    assert payload["totalPages"] == 1


@pytest.mark.asyncio
async def test_search_knowledge_base_returns_trimmed_structured_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AgentToolRegistry(db=object())
    captured: dict[str, object] = {}

    async def fake_embedding(query: str):
        captured["embedding_query"] = query
        return [0.1, 0.2]

    async def fake_search(**kwargs):
        captured["category"] = kwargs.get("category")
        captured["limit"] = kwargs.get("limit")
        return [
            KnowledgeSource(
                source_id="kb-1",
                title="Shipping Policy",
                content_snippet="Shipping details.",
                category=" Policy ",
                relevance=0.95,
                url="https://example.com/shipping",
            ),
            KnowledgeSource(
                source_id="kb-2",
                title="Returns Policy",
                content_snippet="Returns details.",
                category="Policy",
                relevance=0.82,
                url="https://example.com/returns",
            ),
        ]

    monkeypatch.setattr(llm_service, "generate_embedding", fake_embedding)
    registry._knowledge_retrieval.search = fake_search  # type: ignore[attr-defined]

    payload = await registry.search_knowledge_base(
        SearchKnowledgeBaseArgs(query="what is your shipping policy?", category=" Policy ", limit=1)
    )

    assert captured["embedding_query"] == "what is your shipping policy?"
    assert captured["category"] == "Policy"
    assert payload["tool"] == "search_knowledge_base"
    assert payload["status"] == "ok"
    assert payload["source"] == "knowledge_db"
    assert payload["category"] == "Policy"
    assert payload["limit"] == 1
    assert payload["totalItems"] == 1
    assert payload["items"][0]["category"] == "Policy"
    assert payload["items"][0]["source_id"] == "kb-1"

