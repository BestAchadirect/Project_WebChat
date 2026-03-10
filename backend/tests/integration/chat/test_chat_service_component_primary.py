from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatRequest
from app.services.chat.service import ChatService
from tests.fixtures.chat import build_component_pipeline_result, patch_chat_service_lifecycle


@pytest.mark.asyncio
async def test_chat_service_component_mode_returns_component_pipeline_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id):
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
    async def failing_component_pipeline(self, *, request, conversation_id, run_id):
        raise RuntimeError("pipeline failed")

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", failing_component_pipeline)

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-2", message="list steel rings", locale="en-US"),
        channel="widget",
    )

    assert response.intent == "fallback_general"
    assert response.meta is not None
    assert response.meta.source == "error"
    assert any(component.type.value == "error" for component in response.components)


@pytest.mark.asyncio
async def test_chat_service_component_primary_runs_for_non_widget_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_component_pipeline(self, *, request, conversation_id, run_id):
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
    async def fake_component_pipeline(self, *, request, conversation_id, run_id):
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
    monkeypatch.setattr(ChatService, "_run_nlu", should_not_run_legacy_nlu)

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
    async def failing_component_pipeline(self, *, request, conversation_id, run_id):
        raise RuntimeError("component pipeline failed")

    async def should_not_run_legacy_nlu(self, **kwargs):
        raise AssertionError("legacy runtime should not be used as an error recovery path")

    patch_chat_service_lifecycle(monkeypatch)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", failing_component_pipeline)
    monkeypatch.setattr(ChatService, "_run_nlu", should_not_run_legacy_nlu)

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-2", message="show titanium labrets", locale="en-US"),
        channel="widget",
    )

    assert response.intent == "fallback_general"
    assert response.meta is not None
    assert response.meta.source == "error"
    assert response.debug.get("component_mode") == "error"
    assert "component pipeline failed" in str(response.debug.get("component_pipeline_error") or "")
