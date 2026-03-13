from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")

from app.schemas.chat import ProductCard
from app.services.chat import sku_precheck


def card(sku: str) -> ProductCard:
    return ProductCard(
        id=uuid4(),
        object_id=sku,
        sku=sku,
        legacy_sku=[],
        name=sku,
        price=10.0,
        currency="USD",
        stock_status="in_stock",
        image_url=None,
        product_url=None,
        attributes={},
    )


def test_sku_precheck_allows_simple_single_sku_lookup() -> None:
    should_run, reason, candidates = sku_precheck.should_run_sku_precheck(
        user_text="BLK466-F02A12",
        channel="widget",
    )

    assert should_run is True
    assert reason == ""
    assert candidates == ["blk466-f02a12"]


def test_sku_precheck_bypasses_multi_sku_compare_text_as_multi_token_query() -> None:
    should_run, reason, candidates = sku_precheck.should_run_sku_precheck(
        user_text="compare BLK466-F02A12 vs BLK466-F04A12",
        channel="widget",
    )

    assert should_run is False
    assert reason == "requires_single_sku_token"
    assert len(candidates) == 2


def test_sku_precheck_bypasses_image_requests() -> None:
    should_run, reason, candidates = sku_precheck.should_run_sku_precheck(
        user_text="show image for SKU BLK466-F02A12",
        channel="widget",
    )

    assert should_run is False
    assert reason == "image_requested"
    assert candidates == []


def test_sku_precheck_bypasses_multi_sku_queries_without_control_keywords() -> None:
    should_run, reason, candidates = sku_precheck.should_run_sku_precheck(
        user_text="BLK466-F02A12 BLK466-F04A12",
        channel="widget",
    )

    assert should_run is False
    assert reason == "requires_single_sku_token"
    assert len(candidates) == 2


@pytest.mark.asyncio
async def test_cheap_sku_precheck_returns_first_matching_candidate() -> None:
    async def fake_search(*, sku: str, limit: int):
        if sku == "blk466-f02a12":
            return [card("BLK466-F02A12")]
        return []

    candidate, cards = await sku_precheck.cheap_sku_precheck(
        user_text="BLK466-F02A12",
        search_by_exact_sku=fake_search,
        limit=3,
    )
    assert candidate == "blk466-f02a12"
    assert len(cards) == 1
