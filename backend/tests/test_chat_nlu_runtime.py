from __future__ import annotations

import pytest

pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.services.chat import nlu_runtime


class _ServiceStub:
    @staticmethod
    def _extract_sku(text: str):
        return "blk466-f02a12" if "BLK466-F02A12" in text else None

    @staticmethod
    def _infer_jewelry_type_filter(text: str):
        return "Labrets" if "labret" in text.lower() else None

    @staticmethod
    def _log_event(**kwargs):
        return None


def test_heuristic_nlu_fast_path_returns_product_intent() -> None:
    data, confidence = nlu_runtime.heuristic_nlu_fast_path(
        service=_ServiceStub(),
        user_text="Need details for SKU BLK466-F02A12",
        locale="en-US",
    )
    assert data is not None
    assert data["intent"] == "search_specific"
    assert data["show_products"] is True
    assert confidence >= 0.9


@pytest.mark.asyncio
async def test_run_external_call_respects_llm_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 1)
    external_state = {"count": 0, "llm_count": 1, "by_name": {}}
    with pytest.raises(RuntimeError, match="llm call cap exceeded"):
        await nlu_runtime.run_external_call(
            service=_ServiceStub(),
            external_state=external_state,
            call_name="nlu",
            call_factory=lambda: None,
            run_id="run-1",
            debug_meta={},
        )


@pytest.mark.asyncio
async def test_run_nlu_forces_deterministic_fast_path_when_cap_is_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 1)
    monkeypatch.setattr(settings, "NLU_FAST_PATH_ENABLED", True)
    external_state = {"count": 0, "llm_count": 0, "by_name": {}}
    debug_meta = {}
    data = await nlu_runtime.run_nlu(
        service=_ServiceStub(),
        user_text="show labret 14g steel",
        history=[],
        locale="en-US",
        run_id="run-2",
        external_state=external_state,
        debug_meta=debug_meta,
    )
    assert data["show_products"] is True
    assert data["intent"] in {"browse_products", "search_specific"}
    assert debug_meta.get("nlu_fast_path_forced_by_llm_cap") is True


@pytest.mark.asyncio
async def test_resolve_target_currency_uses_supported_nlu_currency() -> None:
    target = await nlu_runtime.resolve_target_currency(
        nlu_data={"currency": "USD"},
        user_text="price in usd",
    )
    assert target == "USD"
