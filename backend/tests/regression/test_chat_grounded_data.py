from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.models.product import StockStatus
from app.services.ai.llm_service import llm_service
from app.services.chat.agentic.orchestrator import AgentOrchestrator
from app.services.chat.agentic.tool_registry import (
    CheckInventoryArgs,
    GetProductDetailsArgs,
    SearchKnowledgeBaseArgs,
    SearchProductsArgs,
)
from tests.fixtures.db_grounding import (
    fetch_seeded_product,
    grounded_db_engine,  # noqa: F401 - imported so pytest discovers the fixture dependency.
    grounded_db_session,  # noqa: F401 - imported so pytest discovers the fixture in this module.
    grounded_seed,  # noqa: F401 - imported so pytest discovers the fixture in this module.
    grounded_query_embedding,
)

pytestmark = [pytest.mark.regression, pytest.mark.db_grounded, pytest.mark.agentic]


async def _fake_embedding(query: str) -> list[float]:
    return grounded_query_embedding(query)


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "name": name,
        "arguments": arguments,
        "raw_arguments": json.dumps(arguments),
    }


@pytest.mark.asyncio
async def test_product_exact_sku_matches_seeded_db_truth(
    grounded_db_session,
    grounded_seed,
) -> None:
    del grounded_seed
    expected = await fetch_seeded_product(grounded_db_session, "EVAL-TI-LAB-1")
    orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="grounded-sku", channel="widget")

    payload = await orchestrator.registry.get_product_details(GetProductDetailsArgs(sku="EVAL-TI-LAB-1"))
    normalized = orchestrator.registry.normalize_tool_result(tool_name="get_product_details", result=payload)

    assert payload["source"] == "catalog_db"
    assert payload["status"] == "ok"
    assert normalized.result_count == 1
    assert len(normalized.products) == 1
    card = normalized.products[0]
    assert card.sku == expected.sku
    assert card.price == expected.price
    assert card.currency == expected.currency
    assert card.stock_status == StockStatus.in_stock.value
    assert card.attributes["material"] == expected.attributes["material"]


@pytest.mark.asyncio
async def test_product_filter_search_returns_only_matching_seeded_db_products(
    monkeypatch: pytest.MonkeyPatch,
    grounded_db_session,
    grounded_seed,
) -> None:
    del grounded_seed
    monkeypatch.setattr(llm_service, "generate_embedding", _fake_embedding)
    orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="grounded-filter", channel="widget")

    payload = await orchestrator.registry.search_products(
        SearchProductsArgs.model_validate(
            {
                "query": "titanium labrets",
                "filters": {"material": "titanium", "jewelry_type": "labret"},
                "page": 1,
                "pageSize": 5,
            }
        )
    )
    normalized = orchestrator.registry.normalize_tool_result(tool_name="search_products", result=payload)

    assert payload["source"] == "catalog_db"
    assert payload["status"] == "ok"
    assert [card.sku for card in normalized.products] == ["EVAL-TI-LAB-1"]
    assert all(card.attributes.get("material") == "titanium" for card in normalized.products)
    assert all(card.attributes.get("jewelry_type") == "labret" for card in normalized.products)


@pytest.mark.asyncio
async def test_inventory_truth_does_not_mark_seeded_out_of_stock_product_available(
    grounded_db_session,
    grounded_seed,
) -> None:
    del grounded_seed
    expected = await fetch_seeded_product(grounded_db_session, "EVAL-GOLD-LAB-1")
    orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="grounded-inventory", channel="widget")

    payload = await orchestrator.registry.check_inventory_db(CheckInventoryArgs(sku="EVAL-GOLD-LAB-1"))

    assert expected.stock_status == StockStatus.out_of_stock
    assert payload["source"] == "db"
    assert payload["status"] == "ok"
    assert payload["found"] is True
    assert payload["sku"] == expected.sku
    assert payload["stock_status"] == StockStatus.out_of_stock.value
    assert payload["stock_status"] != StockStatus.in_stock.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_title", "expected_phrase"),
    [
        ("What is your shipping policy?", "Eval Shipping Policy", "3 to 5 business days"),
        ("Can I return opened jewelry?", "Eval Returns Policy", "30 days"),
        ("What payment methods do you accept?", "Eval Payment Policy", "ACH bank transfer"),
    ],
)
async def test_knowledge_policy_sources_match_seeded_db_chunks(
    monkeypatch: pytest.MonkeyPatch,
    grounded_db_session,
    grounded_seed,
    query: str,
    expected_title: str,
    expected_phrase: str,
) -> None:
    del grounded_seed
    monkeypatch.setattr(llm_service, "generate_embedding", _fake_embedding)
    orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="grounded-knowledge", channel="widget")

    payload = await orchestrator.registry.search_knowledge_base(
        SearchKnowledgeBaseArgs(query=query, category="Policy", limit=1)
    )
    normalized = orchestrator.registry.normalize_tool_result(tool_name="search_knowledge_base", result=payload)

    assert payload["source"] == "knowledge_db"
    assert payload["status"] == "ok"
    assert normalized.result_count == 1
    assert len(normalized.sources) == 1
    assert normalized.sources[0].title == expected_title
    assert expected_phrase.lower() in normalized.sources[0].content_snippet.lower()


@pytest.mark.asyncio
async def test_multi_topic_agent_response_is_grounded_in_seeded_product_and_policy(
    monkeypatch: pytest.MonkeyPatch,
    grounded_db_session,
    grounded_seed,
) -> None:
    del grounded_seed
    calls = [
        {
            "content": "",
            "tool_calls": [
                _tool_call("call_product", "get_product_details", {"sku": "EVAL-TI-LAB-1"}),
                _tool_call("call_returns", "search_knowledge_base", {"query": "returns policy", "category": "Policy", "limit": 1}),
            ],
        },
        {
            "content": "EVAL-TI-LAB-1 is in stock at USD 19.50. Unopened jewelry can be returned within 30 days.",
            "tool_calls": [],
        },
    ]

    async def fake_chat_with_tools(**kwargs):
        del kwargs
        return calls.pop(0)

    monkeypatch.setattr(llm_service, "generate_embedding", _fake_embedding)
    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_chat_with_tools)
    orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="grounded-multi", channel="widget")

    result = await orchestrator.run(user_text="Is EVAL-TI-LAB-1 available, and what is your return policy?")

    assert result.used_tools is True
    assert "EVAL-TI-LAB-1" in result.final_reply
    assert "19.50" in result.final_reply
    assert "30 days" in result.final_reply
    assert [card.sku for card in result.product_carousel] == ["EVAL-TI-LAB-1"]
    assert [source.title for source in result.sources] == ["Eval Returns Policy"]


@pytest.mark.asyncio
async def test_context_follow_up_can_resolve_gold_seeded_variant(
    monkeypatch: pytest.MonkeyPatch,
    grounded_db_session,
    grounded_seed,
) -> None:
    del grounded_seed
    calls = [
        {
            "content": "",
            "tool_calls": [_tool_call("call_gold", "get_product_details", {"sku": "EVAL-GOLD-LAB-1"})],
        },
        {
            "content": "The gold labret variant is EVAL-GOLD-LAB-1 and it is out of stock at USD 24.00.",
            "tool_calls": [],
        },
    ]

    async def fake_chat_with_tools(**kwargs):
        del kwargs
        return calls.pop(0)

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_chat_with_tools)
    orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="grounded-context", channel="widget")

    result = await orchestrator.run(
        user_text="What about the gold one?",
        history=[
            {"role": "user", "content": "Show me the titanium labret."},
            {"role": "assistant", "content": "EVAL-TI-LAB-1 is the titanium labret."},
        ],
    )

    assert "gold labret" in result.final_reply.lower()
    assert "out of stock" in result.final_reply.lower()
    assert [card.sku for card in result.product_carousel] == ["EVAL-GOLD-LAB-1"]
    assert result.product_carousel[0].stock_status == StockStatus.out_of_stock.value


@pytest.mark.asyncio
async def test_context_follow_up_can_resolve_pronoun_to_seeded_titanium_variant(
    monkeypatch: pytest.MonkeyPatch,
    grounded_db_session,
    grounded_seed,
) -> None:
    del grounded_seed
    calls = [
        {
            "content": "",
            "tool_calls": [_tool_call("call_titanium", "get_product_details", {"sku": "EVAL-TI-LAB-1"})],
        },
        {
            "content": "The titanium labret EVAL-TI-LAB-1 is in stock at USD 19.50.",
            "tool_calls": [],
        },
    ]

    async def fake_chat_with_tools(**kwargs):
        del kwargs
        return calls.pop(0)

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_chat_with_tools)
    orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="grounded-pronoun", channel="widget")

    result = await orchestrator.run(
        user_text="How much is it?",
        history=[
            {"role": "user", "content": "Show me the titanium labret."},
            {"role": "assistant", "content": "EVAL-TI-LAB-1 is the titanium labret."},
        ],
    )

    assert "titanium labret" in result.final_reply.lower()
    assert "in stock" in result.final_reply.lower()
    assert [card.sku for card in result.product_carousel] == ["EVAL-TI-LAB-1"]
    assert result.product_carousel[0].stock_status == StockStatus.in_stock.value


@pytest.mark.asyncio
async def test_context_follow_up_can_keep_policy_anchor_after_topic_shift(
    monkeypatch: pytest.MonkeyPatch,
    grounded_db_session,
    grounded_seed,
) -> None:
    del grounded_seed
    calls = [
        {
            "content": "",
            "tool_calls": [
                _tool_call(
                    "call_returns",
                    "search_knowledge_base",
                    {"query": "returns policy", "category": "Policy", "limit": 1},
                )
            ],
        },
        {
            "content": "Eligible jewelry can be returned within 30 days.",
            "tool_calls": [],
        },
    ]

    async def fake_chat_with_tools(**kwargs):
        del kwargs
        return calls.pop(0)

    monkeypatch.setattr(llm_service, "generate_embedding", _fake_embedding)
    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_chat_with_tools)
    orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="grounded-policy", channel="widget")

    result = await orchestrator.run(
        user_text="What about returns?",
        history=[
            {"role": "user", "content": "Tell me about shipping."},
            {"role": "assistant", "content": "Shipping depends on destination and service level."},
        ],
    )

    assert "30 days" in result.final_reply.lower()
    assert [source.title for source in result.sources] == ["Eval Returns Policy"]
    assert [card.sku for card in result.product_carousel] == []


@pytest.mark.asyncio
async def test_negative_grounding_unknown_product_returns_not_found_without_artifacts(
    grounded_db_session,
    grounded_seed,
) -> None:
    del grounded_seed
    orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="grounded-negative", channel="widget")

    payload = await orchestrator.registry.get_product_details(GetProductDetailsArgs(sku="EVAL-UNKNOWN-404"))
    normalized = orchestrator.registry.normalize_tool_result(tool_name="get_product_details", result=payload)

    assert payload["source"] == "catalog_db"
    assert payload["status"] == "not_found"
    assert payload["found"] is False
    assert normalized.result_count == 0
    assert normalized.products == []
