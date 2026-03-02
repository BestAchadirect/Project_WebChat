from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")

from app.schemas.chat import ProductCard
from app.services.chat import sku_precheck
from app.services.chat.service import ChatService


def _card(sku: str) -> ProductCard:
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


def test_should_run_sku_precheck_requires_single_code() -> None:
    should_run, reason, candidates = sku_precheck.should_run_sku_precheck(
        user_text="BLK466-F02A12",
        channel="widget",
    )
    assert should_run is True
    assert reason == ""
    assert candidates == ["blk466-f02a12"]


def test_should_run_sku_precheck_bypasses_compare_text() -> None:
    should_run, reason, candidates = sku_precheck.should_run_sku_precheck(
        user_text="compare BLK466-F02A12 vs BLK466-F04A12",
        channel="widget",
    )
    assert should_run is False
    assert reason == "compare_requested"
    assert candidates == []


@pytest.mark.asyncio
async def test_cheap_sku_precheck_returns_first_matching_candidate() -> None:
    async def fake_search(*, sku: str, limit: int):
        if sku == "blk466-f02a12":
            return [_card("BLK466-F02A12")]
        return []

    candidate, cards = await sku_precheck.cheap_sku_precheck(
        user_text="BLK466-F02A12",
        search_by_exact_sku=fake_search,
        limit=3,
    )
    assert candidate == "blk466-f02a12"
    assert len(cards) == 1


def test_chat_service_should_run_sku_precheck_wrapper_compatible() -> None:
    service = ChatService(db=object())
    should_run, reason, candidates = service._should_run_sku_precheck(
        user_text="BLK466-F02A12",
        channel="widget",
    )
    assert should_run is True
    assert reason == ""
    assert candidates == ["blk466-f02a12"]
