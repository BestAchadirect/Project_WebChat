import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")
pytestmark = pytest.mark.agentic

from app.core.config import settings
from app.schemas.chat import ProductCard
from app.services.chat.agentic.orchestrator import AgentOrchestrator, AgentRunInput, AgentRunOutcome
from app.services.chat.agentic.tool_registry import AgentToolRegistry
from app.services.ai.llm_service import llm_service


@pytest.mark.asyncio
async def test_orchestrator_executes_tool_then_finalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGENTIC_MAX_TOOL_ROUNDS", 4)
    monkeypatch.setattr(settings, "AGENTIC_MAX_TOOL_CALLS", 6)
    monkeypatch.setattr(settings, "AGENTIC_MAX_TOOL_RESULT_ITEMS", 10)
    monkeypatch.setattr(settings, "AGENTIC_TOOL_TIMEOUT_MS", 3500)

    call_count = {"value": 0}

    async def fake_generate_chat_with_tools(**kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "check_inventory_db",
                        "arguments": {"sku": "ABC-1"},
                        "raw_arguments": "{\"sku\":\"ABC-1\"}",
                        "argument_error": None,
                    }
                ],
                "finish_reason": "tool_calls",
            }
        return {
            "content": "SKU ABC-1 is currently in stock.",
            "tool_calls": [],
            "finish_reason": "stop",
        }

    async def fake_execute_tool(self, tool_name, raw_arguments):
        assert tool_name == "check_inventory_db"
        assert raw_arguments == {"sku": "ABC-1"}
        return {
            "found": True,
            "sku": "ABC-1",
            "stock_status": "in_stock",
            "last_stock_sync_at": "2026-02-19T00:00:00",
            "source": "db",
        }

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_generate_chat_with_tools)
    monkeypatch.setattr(AgentToolRegistry, "execute_tool", fake_execute_tool)

    orchestrator = AgentOrchestrator(db=None, run_id="run-1", channel="widget")
    result = await orchestrator.run(
        request=AgentRunInput(
            user_text="Is ABC-1 in stock?",
            history=[],
            reply_language="en-US",
            channel="widget",
            run_id="run-1",
        ),
    )

    assert result.outcome == AgentRunOutcome.TOOL_SUCCESS
    assert result.used_tools is True
    assert "in stock" in result.final_reply.lower()
    assert len(result.trace) == 1
    assert result.trace[0]["tool"] == "check_inventory_db"
    assert result.trace[0]["status"] == "ok"
    assert result.trace[0]["tool_status"] == "ok"


@pytest.mark.asyncio
async def test_orchestrator_returns_typed_artifacts_from_normalized_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENTIC_MAX_TOOL_ROUNDS", 4)
    monkeypatch.setattr(settings, "AGENTIC_MAX_TOOL_CALLS", 6)
    monkeypatch.setattr(settings, "AGENTIC_MAX_TOOL_RESULT_ITEMS", 10)
    monkeypatch.setattr(settings, "AGENTIC_TOOL_TIMEOUT_MS", 3500)

    call_count = {"value": 0}

    async def fake_generate_chat_with_tools(**kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "search_products",
                        "arguments": {"query": "titanium labret"},
                        "raw_arguments": "{\"query\":\"titanium labret\"}",
                        "argument_error": None,
                    }
                ],
                "finish_reason": "tool_calls",
            }
        return {
            "content": "I found a matching titanium labret.",
            "tool_calls": [],
            "finish_reason": "stop",
        }

    async def fake_execute_tool(self, tool_name, raw_arguments):
        assert tool_name == "search_products"
        return {
            "tool": "search_products",
            "status": "ok",
            "source": "catalog_db",
            "items": [
                {
                    "id": "66666666-6666-6666-6666-666666666666",
                    "sku": "TI-LAB-1",
                    "legacy_sku": [],
                    "name": "Titanium Labret",
                    "price": 19.0,
                    "currency": "USD",
                    "stock_status": "in_stock",
                    "attributes": {"material": "Titanium"},
                }
            ],
            "totalItems": 1,
        }

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_generate_chat_with_tools)
    monkeypatch.setattr(AgentToolRegistry, "execute_tool", fake_execute_tool)

    orchestrator = AgentOrchestrator(db=None, run_id="run-products", channel="widget")
    result = await orchestrator.run(user_text="show titanium labrets", history=[], reply_language="en-US")

    assert result.outcome == AgentRunOutcome.TOOL_SUCCESS
    assert len(result.product_carousel) == 1
    assert isinstance(result.product_carousel[0], ProductCard)
    assert result.product_carousel[0].sku == "TI-LAB-1"
    assert result.trace[0]["result_count"] == 1


@pytest.mark.asyncio
async def test_orchestrator_returns_explicit_empty_result_when_no_tool_and_no_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_with_tools(**kwargs):
        return {"content": "", "tool_calls": [], "finish_reason": "stop"}

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_generate_chat_with_tools)

    orchestrator = AgentOrchestrator(db=None, run_id="run-2", channel="widget")
    result = await orchestrator.run(
        user_text="hello",
        history=[],
        reply_language="en-US",
    )

    assert result.outcome == AgentRunOutcome.EMPTY
    assert result.used_tools is False
    assert result.fallback_reason == "empty_result"


@pytest.mark.asyncio
async def test_orchestrator_returns_explicit_no_tool_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_with_tools(**kwargs):
        return {
            "content": "I can help with products, stock, and store information.",
            "tool_calls": [],
            "finish_reason": "stop",
        }

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_generate_chat_with_tools)

    orchestrator = AgentOrchestrator(db=None, run_id="run-no-tool", channel="widget")
    result = await orchestrator.run(user_text="what can you do?", history=[], reply_language="en-US")

    assert result.outcome == AgentRunOutcome.NO_TOOL_ANSWER
    assert result.used_tools is False
    assert result.fallback_reason == "no_tool_usage"

