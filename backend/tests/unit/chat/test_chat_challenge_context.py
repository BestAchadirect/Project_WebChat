from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.chat import challenge_context


def test_resolver_disabled_by_flag_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CHALLENGE_CONTEXT_ENABLED", False)
    decision = challenge_context.resolve_challenge_context(
        user_text="Are you sure?",
        channel="widget",
        state_raw={},
        history=[],
        sku_tokens=[],
    )
    assert decision.mode == "none"
    assert decision.active is False


def test_stock_dispute_prefers_explicit_sku_over_state_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CHALLENGE_CONTEXT_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_CHALLENGE_CONTEXT_CHANNELS", "widget,qa_console")
    state = {
        "last_inventory_claim": {"sku": "STATE-1"},
        "last_product_skus": ["STATE-2"],
    }
    history = [
        {
            "role": "assistant",
            "content": "prior",
            "product_data": [{"sku": "HISTORY-1"}],
        }
    ]
    decision = challenge_context.resolve_challenge_context(
        user_text="This is not ok, your inventory is wrong.",
        channel="widget",
        state_raw=state,
        history=history,
        sku_tokens=["TEXT-1"],
    )
    assert decision.mode == "inventory_reverify"
    assert decision.target_sku == "TEXT-1"


def test_confirmation_challenge_on_knowledge_uses_base_question(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CHALLENGE_CONTEXT_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_CHALLENGE_CONTEXT_CHANNELS", "widget,qa_console")
    state = {
        "last_workflow": "knowledge",
        "last_user_query": "What is your company?",
    }
    decision = challenge_context.resolve_challenge_context(
        user_text="Are you sure about that?",
        channel="widget",
        state_raw=state,
        history=[],
        sku_tokens=[],
    )
    assert decision.mode == "knowledge_reconfirm"
    assert decision.base_question == "What is your company?"


def test_stock_dispute_without_target_requests_clarification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CHALLENGE_CONTEXT_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_CHALLENGE_CONTEXT_CHANNELS", "widget,qa_console")
    decision = challenge_context.resolve_challenge_context(
        user_text="Inventory is wrong and this is not ok.",
        channel="widget",
        state_raw={},
        history=[],
        sku_tokens=[],
    )
    assert decision.mode == "needs_target_clarification"
    assert decision.reason == "stock_dispute_missing_target"


def test_channel_gate_blocks_challenge_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CHALLENGE_CONTEXT_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_CHALLENGE_CONTEXT_CHANNELS", "widget,qa_console")
    decision = challenge_context.resolve_challenge_context(
        user_text="Are you sure?",
        channel="internal_tool",
        state_raw={"last_workflow": "knowledge", "last_user_query": "Where are you located?"},
        history=[],
        sku_tokens=[],
    )
    assert decision.mode == "none"

