from __future__ import annotations

import pytest

pytest.importorskip("pydantic_settings")

from app.services.chat.service import ChatService


def _service() -> ChatService:
    return ChatService(db=object())


def test_sku_precheck_allows_simple_single_sku_lookup() -> None:
    service = _service()
    should_run, reason, candidates = service._should_run_sku_precheck(
        user_text="BLK466-F02A12",
        channel="widget",
    )
    assert should_run is True
    assert reason == ""
    assert candidates == ["blk466-f02a12"]


def test_sku_precheck_bypasses_compare_requests() -> None:
    service = _service()
    should_run, reason, candidates = service._should_run_sku_precheck(
        user_text="Compare SKU BLK466-F02A12 and SKU BLK466-F04A12",
        channel="widget",
    )
    assert should_run is False
    assert reason == "compare_requested"
    assert candidates == []


def test_sku_precheck_bypasses_image_requests() -> None:
    service = _service()
    should_run, reason, candidates = service._should_run_sku_precheck(
        user_text="show image for SKU BLK466-F02A12",
        channel="widget",
    )
    assert should_run is False
    assert reason == "image_requested"
    assert candidates == []


def test_sku_precheck_bypasses_multi_sku_queries_without_control_keywords() -> None:
    service = _service()
    should_run, reason, candidates = service._should_run_sku_precheck(
        user_text="BLK466-F02A12 BLK466-F04A12",
        channel="widget",
    )
    assert should_run is False
    assert reason == "requires_single_sku_token"
    assert len(candidates) == 2
