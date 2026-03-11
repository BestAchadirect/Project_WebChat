from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.services.chat.agentic.orchestrator import AgentRunResult
from app.services.chat.service import ChatService
from tests.fixtures.chat import build_component_pipeline_result, patch_chat_service_lifecycle


@pytest.mark.asyncio
async def test_chat_service_component_mode_returns_component_pipeline_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        route_override = kwargs.get("route_decision_override")
        assert route_override is not None
        assert str(getattr(route_override, "workflow", "")) in {
            "catalog",
            "knowledge",
            "comparison",
            "recommendation",
            "smalltalk",
            "fallback",
        }
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="component response",
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-1", message="list steel rings", locale="en-US"),
        channel="widget",
    )

    assert response.reply_text == "component response"
    assert response.debug.get("component_mode") == "primary"
    assert response.debug.get("component_plan") == ["query_summary"]


@pytest.mark.asyncio
async def test_chat_service_component_primary_returns_component_error_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        raise RuntimeError("pipeline failed")

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", failing_component_pipeline)

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-2", message="list steel rings", locale="en-US"),
        channel="widget",
    )

    assert response.routing.workflow == "fallback"
    assert response.meta is not None
    assert response.meta.source == "error"
    assert any(component.type.value == "error" for component in response.components)


@pytest.mark.asyncio
async def test_chat_service_component_primary_runs_for_non_widget_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="component response qa",
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-3", message="list steel rings", locale="en-US"),
        channel="qa_console",
    )

    assert response.reply_text == "component response qa"
    assert response.debug.get("component_channel_allowed") is True
    assert response.debug.get("component_mode") == "primary"


@pytest.mark.asyncio
async def test_process_chat_uses_component_primary_runtime_without_legacy_nlu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="component-primary response",
            component_text=request.message,
        )

    async def should_not_run_legacy_nlu(self, **kwargs):
        raise AssertionError("legacy NLU should not be used by the component-primary runtime")

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)
    monkeypatch.setattr(ChatService, "_run_nlu", should_not_run_legacy_nlu, raising=False)

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-1", message="show titanium labrets", locale="en-US"),
        channel="widget",
    )

    assert response.reply_text == "component-primary response"
    assert response.debug.get("component_mode") == "primary"
    assert response.debug.get("component_plan") == ["query_summary"]


@pytest.mark.asyncio
async def test_process_chat_component_pipeline_failure_returns_error_without_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        raise RuntimeError("component pipeline failed")

    async def should_not_run_legacy_nlu(self, **kwargs):
        raise AssertionError("legacy runtime should not be used as an error recovery path")

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", failing_component_pipeline)
    monkeypatch.setattr(ChatService, "_run_nlu", should_not_run_legacy_nlu, raising=False)

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-2", message="show titanium labrets", locale="en-US"),
        channel="widget",
    )

    assert response.routing.workflow == "fallback"
    assert response.meta is not None
    assert response.meta.source == "error"
    assert response.debug.get("component_mode") == "error"
    assert "component pipeline failed" in str(response.debug.get("component_pipeline_error") or "")


@pytest.mark.asyncio
async def test_process_chat_uses_agentic_workflow_when_eligible(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_agentic_workflow(
        self,
        *,
        user_text: str,
        conversation_id: int,
        run_id: str,
        channel: str,
        reply_language: str,
    ):
        assert "stock" in user_text.lower()
        assert channel == "widget"
        return AgentRunResult(
            final_reply="ABC-1 is currently in stock.",
            used_tools=True,
            product_carousel=[],
            sources=[],
            trace=[{"tool": "check_inventory_db", "status": "ok"}],
        )

    async def should_not_run_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        raise AssertionError("component pipeline should not run when agentic flow succeeds")

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")
    monkeypatch.setattr(ChatService, "_run_agentic_workflow", fake_agentic_workflow)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", should_not_run_component_pipeline)

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-agent-1", message="check stock for ABC-1", locale="en-US"),
        channel="widget",
    )

    assert response.reply_text == "ABC-1 is currently in stock."
    assert response.debug.get("component_mode") == "agentic"
    assert response.debug.get("execution_mode") == "agentic"
    assert bool((response.debug.get("agentic") or {}).get("used_tools")) is True


@pytest.mark.asyncio
async def test_process_chat_falls_back_to_component_when_agentic_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_agentic_workflow(
        self,
        *,
        user_text: str,
        conversation_id: int,
        run_id: str,
        channel: str,
        reply_language: str,
    ):
        return None

    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="component fallback response",
        )

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget")
    monkeypatch.setattr(ChatService, "_run_agentic_workflow", fake_agentic_workflow)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-agent-2", message="stock for ABC-1", locale="en-US"),
        channel="widget",
    )

    assert response.reply_text == "component fallback response"
    assert response.debug.get("component_mode") == "primary"
    assert bool((response.debug.get("agentic") or {}).get("fallback_to_component")) is True
