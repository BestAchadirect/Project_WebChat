from __future__ import annotations

from typing import Any

import pytest

from app.services.ai.llm_service import llm_service
from app.services.chat.routing.understanding import build_understanding_result


@pytest.mark.asyncio
async def test_understanding_detects_company_info() -> None:
    result = await build_understanding_result(
        user_text="Where is the company?",
        locale="en-US",
        channel="widget",
    )

    assert result.workflow_hypothesis == "company_info"
    assert result.knowledge_query == "where is your company located"
    assert result.store_overview_request is True
    assert result.llm_call_count == 0


@pytest.mark.asyncio
async def test_understanding_reuses_shared_contact_signal_vocabulary() -> None:
    result = await build_understanding_result(
        user_text="I want to talk to a sale person",
        locale="en-US",
        channel="widget",
    )

    assert result.workflow_hypothesis == "company_info"
    assert result.knowledge_query == "how can I contact customer service"


@pytest.mark.asyncio
async def test_understanding_detects_policy_info() -> None:
    result = await build_understanding_result(
        user_text="What is your shipping policy?",
        locale="en-US",
        channel="widget",
    )

    assert result.workflow_hypothesis == "policy_info"
    assert result.knowledge_query == "what is your shipping policy?"
    assert result.needs_knowledge is True


@pytest.mark.asyncio
async def test_understanding_detects_catalog_search() -> None:
    result = await build_understanding_result(
        user_text="show me titanium labrets",
        locale="en-US",
        channel="widget",
    )

    assert result.workflow_hypothesis == "catalog_search"
    assert result.needs_products is True


@pytest.mark.asyncio
async def test_understanding_detects_product_detail_from_sku() -> None:
    result = await build_understanding_result(
        user_text="stock for ABC-1",
        locale="en-US",
        channel="widget",
        sku_tokens=["ABC-1"],
    )

    assert result.workflow_hypothesis == "product_detail"
    assert result.needs_products is True


@pytest.mark.asyncio
async def test_understanding_detects_mixed_request() -> None:
    result = await build_understanding_result(
        user_text="Show me titanium jewelry and what payment methods do you accept?",
        locale="en-US",
        channel="widget",
    )

    assert result.workflow_hypothesis == "mixed"
    assert result.needs_products is True
    assert result.needs_knowledge is True


@pytest.mark.asyncio
async def test_understanding_detects_smalltalk() -> None:
    result = await build_understanding_result(
        user_text="Hi",
        locale="en-US",
        channel="widget",
    )

    assert result.workflow_hypothesis == "smalltalk"
    assert result.intent_confidence == pytest.approx(0.96)


@pytest.mark.asyncio
async def test_understanding_uses_llm_for_off_topic_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {"count": 0}

    async def fake_generate_chat_json(*args, **kwargs):
        calls["count"] += 1
        return {
            "workflow_hypothesis": "off_topic",
            "needs_products": False,
            "needs_knowledge": False,
            "store_overview_request": False,
            "knowledge_query": "",
            "reason": "off topic",
            "confidence": 0.82,
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await build_understanding_result(
        user_text="Can you debug my Python script?",
        locale="en-US",
        channel="widget",
    )

    assert calls["count"] == 1
    assert result.workflow_hypothesis == "off_topic"
    assert result.llm_call_count == 1


@pytest.mark.asyncio
async def test_understanding_preserves_failure_reason_when_llm_classification_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(*args, **kwargs):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await build_understanding_result(
        user_text="Can you help with an unusual request?",
        locale="en-US",
        channel="widget",
    )

    assert result.workflow_hypothesis == "clarify"
    assert result.reason == "routing_fallback"
    assert result.failure_reason == "understanding_failed:runtimeerror"
