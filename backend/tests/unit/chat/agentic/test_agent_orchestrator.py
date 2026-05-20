from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")
pytestmark = pytest.mark.agentic

from app.services.ai.llm_service import llm_service
from app.schemas.chat import KnowledgeSource, ProductCard
from app.services.chat.agentic.orchestrator import AgentOrchestrator, AgentRunInput
from app.services.chat.agentic.tool_registry import AgentToolRegistry, NormalizedAgentToolResult
from app.services.chat.runtime.search_plan import SearchPlan


def test_result_count_counts_candidates_for_ambiguous_lookup() -> None:
    count = AgentToolRegistry._result_count(
        {
            "tool": "get_product_details",
            "status": "ambiguous",
            "candidates": [{}, {}, {}],
        }
    )

    assert count == 3


def test_merge_tool_artifacts_keeps_ambiguous_candidates_renderable() -> None:
    orchestrator = AgentOrchestrator(db=object(), run_id="run-1", channel="widget")
    products: dict[str, ProductCard] = {}
    sources = {}

    normalized = orchestrator.registry.normalize_tool_result(
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
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "sku": "LAB-14-ALT",
                    "legacy_sku": [],
                    "name": "LAB-14 Alt",
                    "price": 12.0,
                    "currency": "USD",
                    "stock_status": "out_of_stock",
                    "attributes": {"material": "Steel"},
                },
            ],
        },
    )
    orchestrator._merge_tool_artifacts(
        normalized=normalized,
        products=products,
        sources=sources,
    )

    assert len(products) == 2
    assert all(isinstance(card, ProductCard) for card in products.values())


def test_deterministic_tool_reply_uses_knowledge_artifacts() -> None:
    reply = AgentOrchestrator._deterministic_tool_reply(
        products=[],
        sources=[
            KnowledgeSource(
                source_id="shipping",
                title="Shipping Policy",
                content_snippet="Shipping usually takes 3-5 business days.",
                relevance=0.82,
            )
        ],
        trace=[{"tool": "search_knowledge_base", "tool_status": "ok", "result_count": 1}],
    )

    assert reply == "Here is what I found in Shipping Policy: Shipping usually takes 3-5 business days."


def test_tool_args_from_search_plan_replaces_invented_catalog_filters() -> None:
    args = AgentOrchestrator._tool_args_from_search_plan(
        tool_name="search_products",
        args={
            "query": "opal labret",
            "filters": {"material": "opal", "jewelry_type": "labret"},
            "page": 2,
            "pageSize": 20,
        },
        request=AgentRunInput(
            user_text="Do you guys have any black opal labrets?",
            search_plan=SearchPlan(
                workflow="catalog",
                required_filters={"category": "labrets", "color": "black"},
                semantic_terms=["opal"],
            ),
        ),
    )

    assert args == {
        "query": "labrets black opal",
        "filters": {"category": "labrets", "color": "black"},
        "page": 2,
        "pageSize": 20,
    }


def test_tool_args_from_search_plan_removes_invented_knowledge_category() -> None:
    args = AgentOrchestrator._tool_args_from_search_plan(
        tool_name="search_knowledge_base",
        args={"query": "refund", "category": "products", "limit": 99},
        request=AgentRunInput(
            user_text="What is your return policy?",
            search_plan=SearchPlan(
                workflow="knowledge",
                knowledge_topics=["what is your return policy?"],
            ),
        ),
    )

    assert args == {"query": "what is your return policy?", "limit": 5}


@pytest.mark.asyncio
async def test_orchestrator_uses_search_plan_tool_fallback_when_tool_round_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = ProductCard(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        sku="LAB-TI",
        legacy_sku=[],
        name="Titanium Labret",
        price=12.0,
        currency="USD",
        stock_status="in_stock",
        attributes={"jewelry_type": "Labret", "material": "Titanium"},
    )

    async def failing_tool_round(**_kwargs):
        raise TimeoutError("Request timed out.")

    async def fake_generate_chat_response(**_kwargs):
        return "I found titanium labrets."

    async def fake_execute_one_tool(*, tool_name: str, args: dict):
        assert tool_name == "search_products"
        assert args["query"] == "labret titanium g23"
        assert args["filters"] == {"jewelry_type": "labret", "material": "titanium g23"}
        return {"tool": tool_name, "status": "ok", "products": [{"sku": "LAB-TI"}]}

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", failing_tool_round)
    monkeypatch.setattr(llm_service, "generate_chat_response", fake_generate_chat_response)

    orchestrator = AgentOrchestrator(db=object(), run_id="run-plan-fallback", channel="widget")
    monkeypatch.setattr(orchestrator, "_execute_one_tool", fake_execute_one_tool)
    monkeypatch.setattr(
        orchestrator.registry,
        "normalize_tool_result",
        lambda **_kwargs: NormalizedAgentToolResult(
            tool_name="search_products",
            status="ok",
            result_count=1,
            products=[product],
        ),
    )

    result = await orchestrator.run(
        request=AgentRunInput(
            user_text="Show me titanium labrets",
            reply_language="en-US",
            channel="widget",
            run_id="run-plan-fallback",
            search_plan=SearchPlan(
                workflow="catalog",
                required_filters={"jewelry_type": "labret", "material": "titanium g23"},
            ),
        )
    )

    assert result.used_tools is True
    assert result.final_reply == "I found titanium labrets."
    assert result.product_carousel == [product]
    assert result.trace[0]["tool"] == "search_products"
    assert result.trace[0]["selection_source"] == "search_plan_fallback"
    assert result.trace[0]["args"] == {
        "query": "labret titanium g23",
        "filters": {"jewelry_type": "labret", "material": "titanium g23"},
        "page": 1,
        "pageSize": 10,
    }


@pytest.mark.asyncio
async def test_orchestrator_adds_catalog_tool_guidance_from_search_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def fake_generate_chat_with_tools(**kwargs):
        messages = list(kwargs.get("messages") or [])
        captured["system"] = str(messages[0]["content"] if messages else "")
        return {"content": "", "tool_calls": []}

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_generate_chat_with_tools)
    request = AgentRunInput(
        user_text="show me titanium labrets",
        reply_language="en-US",
        channel="widget",
        run_id="run-guidance-catalog",
        search_plan=SimpleNamespace(
            to_debug_dict=lambda: {
                "workflow": "catalog",
                "required_filters": {"material": "titanium"},
                "semantic_terms": ["labrets"],
                "sku_tokens": [],
                "knowledge_topics": [],
            }
        ),
    )

    orchestrator = AgentOrchestrator(db=object(), run_id="run-guidance-catalog", channel="widget")
    await orchestrator.run(request=request)

    assert "Tool guidance for this turn" in captured["system"]
    assert "search_products" in captured["system"]
    assert "material=titanium" in captured["system"]
    assert "Do not invent extra product filters" in captured["system"]


@pytest.mark.asyncio
async def test_orchestrator_adds_knowledge_tool_guidance_from_search_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def fake_generate_chat_with_tools(**kwargs):
        messages = list(kwargs.get("messages") or [])
        captured["system"] = str(messages[0]["content"] if messages else "")
        return {"content": "", "tool_calls": []}

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_generate_chat_with_tools)
    request = AgentRunInput(
        user_text="what is your shipping policy?",
        reply_language="en-US",
        channel="widget",
        run_id="run-guidance-knowledge",
        search_plan=SimpleNamespace(
            to_debug_dict=lambda: {
                "workflow": "knowledge",
                "required_filters": {},
                "semantic_terms": [],
                "sku_tokens": [],
                "knowledge_topics": ["what is your shipping policy?"],
            }
        ),
    )

    orchestrator = AgentOrchestrator(db=object(), run_id="run-guidance-knowledge", channel="widget")
    await orchestrator.run(request=request)

    assert "Tool guidance for this turn" in captured["system"]
    assert "search_knowledge_base" in captured["system"]


@pytest.mark.asyncio
async def test_orchestrator_forces_final_reply_when_tool_followup_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "search_knowledge_base",
                    "raw_arguments": '{"query": "return policy"}',
                    "arguments": {"query": "return policy"},
                }
            ],
        },
        {"content": "", "tool_calls": []},
        {"content": "You can request a return within 30 days.", "tool_calls": []},
    ]
    seen_tool_choices: list[str] = []
    final_messages: list[dict] = []

    async def fake_generate_chat_with_tools(**kwargs):
        seen_tool_choices.append(str(kwargs.get("tool_choice") or ""))
        return calls.pop(0)

    async def fake_generate_chat_response(**kwargs):
        final_messages.extend(list(kwargs.get("messages") or []))
        return "You can request a return within 30 days."

    async def fake_execute_one_tool(*, tool_name: str, args: dict):
        assert tool_name == "search_knowledge_base"
        assert args == {"query": "return policy"}
        return {"tool": tool_name, "status": "ok", "sources": [{"source_id": "src-1"}]}

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_generate_chat_with_tools)
    monkeypatch.setattr(llm_service, "generate_chat_response", fake_generate_chat_response)

    orchestrator = AgentOrchestrator(db=object(), run_id="run-final-reply", channel="widget")
    monkeypatch.setattr(orchestrator, "_execute_one_tool", fake_execute_one_tool)
    monkeypatch.setattr(
        orchestrator.registry,
        "normalize_tool_result",
        lambda **_kwargs: NormalizedAgentToolResult(
            tool_name="search_knowledge_base",
            status="ok",
            result_count=1,
        ),
    )

    result = await orchestrator.run(
        request=AgentRunInput(
            user_text="What is your return policy?",
            reply_language="en-US",
            channel="widget",
            run_id="run-final-reply",
        )
    )

    assert result.used_tools is True
    assert result.final_reply == "You can request a return within 30 days."
    assert result.trace == [
        {
            "tool": "search_knowledge_base",
            "status": "ok",
            "tool_status": "ok",
            "duration_ms": result.trace[0]["duration_ms"],
            "result_count": 1,
            "args": {"query": "return policy"},
        }
    ]
    assert seen_tool_choices == ["auto", "auto"]
    assert "Tool result summary" in str(final_messages[2]["content"])
