from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ProductCard
from app.services.chat.retrieval.recommendation_service import RecommendationService


def _card(
    *,
    sku: str,
    name: str,
    price: float,
    stock_status: str = "in_stock",
    attributes: dict | None = None,
) -> ProductCard:
    return ProductCard(
        id=uuid4(),
        object_id=sku,
        sku=sku,
        legacy_sku=[],
        name=name,
        description=None,
        price=price,
        currency="USD",
        stock_status=stock_status,
        image_url=None,
        product_url=None,
        attributes=attributes or {},
    )


class _NoopDB:
    async def execute(self, *args, **kwargs):
        return None


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *args, **kwargs):
        return _FakeScalarResult(self._rows)


def test_rank_product_cards_prefers_stock_filter_and_semantic_signal() -> None:
    best = _card(
        sku="LAB-1",
        name="Titanium Labret One",
        price=8.5,
        attributes={"material": "titanium", "jewelry_type": "labret", "design": "disc"},
    )
    partial = _card(
        sku="LAB-2",
        name="Titanium Labret Two",
        price=9.0,
        stock_status="out_of_stock",
        attributes={"material": "titanium", "jewelry_type": "labret"},
    )
    wrong = _card(
        sku="RING-1",
        name="Gold Ring",
        price=7.0,
        attributes={"material": "gold", "jewelry_type": "ring"},
    )

    service = RecommendationService(db=_NoopDB(), catalog_search=SimpleNamespace())
    ranked = service.rank_product_cards(
        candidates=[wrong, partial, best],
        attribute_filters={"material": "titanium", "jewelry_type": "labret"},
        user_text="recommend titanium labrets",
        distance_by_id={
            str(best.id): 0.12,
            str(partial.id): 0.28,
            str(wrong.id): 0.18,
        },
        anchor_products=[best],
        limit=5,
    )

    assert [item.sku for item in ranked.items[:2]] == ["LAB-1", "LAB-2"]
    assert ranked.meta.get("recommendation_mode") == "similar_items"
    assert ranked.meta.get("recommendation_ranked_count") == 3


def test_rank_product_cards_excludes_anchor_products_when_requested() -> None:
    anchor = _card(
        sku="SKU-1",
        name="Anchor Product",
        price=10.0,
        attributes={"material": "steel", "jewelry_type": "ring"},
    )
    similar = _card(
        sku="SKU-2",
        name="Similar Product",
        price=10.5,
        attributes={"material": "steel", "jewelry_type": "ring"},
    )

    service = RecommendationService(db=_NoopDB(), catalog_search=SimpleNamespace())
    ranked = service.rank_product_cards(
        candidates=[anchor, similar],
        attribute_filters={"material": "steel"},
        user_text="recommend something like SKU-1",
        anchor_products=[anchor],
        exclude_product_ids=[anchor.id],
        limit=5,
    )

    assert [item.sku for item in ranked.items] == ["SKU-2"]


def test_build_complementary_profile_uses_anchor_type_and_compatibility_fields() -> None:
    anchor = _card(
        sku="LAB-1",
        name="Threadless Labret Post",
        price=8.0,
        attributes={"jewelry_type": "Labret", "threading": "threadless", "gauge": "16g"},
    )

    profile = RecommendationService.build_complementary_profile(anchor_products=[anchor])

    assert profile is not None
    assert profile.label == "Labret tops"
    assert "labret tops" in profile.search_query
    assert "threadless" in profile.search_query
    assert "16g" in profile.search_query


def test_rank_product_cards_prefers_compatible_complementary_items() -> None:
    anchor = _card(
        sku="LAB-ANCHOR",
        name="Threadless Labret Post",
        price=8.0,
        attributes={"material": "titanium", "jewelry_type": "Labret", "threading": "threadless", "gauge": "16g"},
    )
    compatible_top = _card(
        sku="TOP-1",
        name="Threadless Heart Top",
        price=5.0,
        attributes={"material": "titanium", "jewelry_type": "Top", "threading": "threadless", "gauge": "16g"},
    )
    wrong_threading_attachment = _card(
        sku="BALL-1",
        name="Externally Threaded Replacement Ball",
        price=3.0,
        attributes={"material": "titanium", "jewelry_type": "Ball", "threading": "external", "gauge": "16g"},
    )
    same_type_labret = _card(
        sku="LAB-2",
        name="Titanium Labret Post",
        price=8.5,
        attributes={"material": "titanium", "jewelry_type": "Labret", "threading": "threadless", "gauge": "16g"},
    )

    service = RecommendationService(db=_NoopDB(), catalog_search=SimpleNamespace())
    ranked = service.rank_product_cards(
        candidates=[same_type_labret, wrong_threading_attachment, compatible_top],
        attribute_filters={"material": "titanium", "jewelry_type": "labret"},
        user_text="What goes with this labret?",
        anchor_products=[anchor],
        limit=5,
    )

    assert [item.sku for item in ranked.items[:2]] == ["TOP-1", "BALL-1"]
    assert ranked.items[-1].sku == "LAB-2"
    assert ranked.meta.get("recommendation_mode") == "complementary_items"
    assert ranked.meta.get("recommendation_complementary_label") == "Labret tops"


@pytest.mark.asyncio
async def test_expand_card_candidates_prefers_anchor_embedding() -> None:
    expected_card = _card(
        sku="SKU-REC",
        name="Recommended Product",
        price=12.0,
        attributes={"material": "titanium", "jewelry_type": "labret"},
    )
    captured = {}

    async def fake_vector_search(*, query_embedding, limit, candidate_limit):
        captured["query_embedding"] = list(query_embedding)
        captured["limit"] = limit
        captured["candidate_limit"] = candidate_limit
        return SimpleNamespace(
            cards=[expected_card],
            distance_by_id={str(expected_card.id): 0.22},
        )

    service = RecommendationService(
        db=_FakeDB([[1.0, 3.0], [3.0, 5.0]]),
        catalog_search=SimpleNamespace(vector_search=fake_vector_search),
    )
    expansion = await service.expand_card_candidates(
        anchor_product_ids=[uuid4(), uuid4()],
        query_embedding=[9.0, 9.0],
        limit=12,
    )

    assert expansion.source == "anchor_embedding"
    assert expansion.used_anchor_embedding is True
    assert expansion.used_query_embedding is False
    assert expansion.product_ids == [str(expected_card.id)]
    assert captured["query_embedding"] == [2.0, 4.0]
