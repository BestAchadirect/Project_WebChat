import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.services.chat.agentic.orchestrator import AgentOrchestrator
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
        user_text="Is ABC-1 in stock?",
        history=[],
        reply_language="en-US",
    )

    assert result is not None
    assert result.used_tools is True
    assert "in stock" in result.final_reply.lower()
    assert len(result.trace) == 1
    assert result.trace[0]["tool"] == "check_inventory_db"
    assert result.trace[0]["status"] == "ok"


@pytest.mark.asyncio
async def test_orchestrator_returns_none_when_no_tool_and_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_generate_chat_with_tools(**kwargs):
        return {"content": "", "tool_calls": [], "finish_reason": "stop"}

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_generate_chat_with_tools)

    orchestrator = AgentOrchestrator(db=None, run_id="run-2", channel="widget")
    result = await orchestrator.run(
        user_text="hello",
        history=[],
        reply_language="en-US",
    )

    assert result is None

