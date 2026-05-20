from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat.runtime import execution_coordinator, unified_chat_runtime
from app.services.chat.service import ChatService


def test_unified_chat_runtime_public_surface_is_process_chat_only() -> None:
    assert unified_chat_runtime.__all__ == ["process_chat"]


def test_runtime_shim_metadata_names_migration_targets() -> None:
    runtime_metadata = unified_chat_runtime._COMPATIBILITY_METADATA
    coordinator_metadata = execution_coordinator._COMPATIBILITY_METADATA

    assert runtime_metadata["import_path"] == "app.services.chat.runtime.unified_chat_runtime.process_chat"
    assert runtime_metadata["migration_target"] == "app.services.chat.harness.chat_harness.ChatHarness"
    assert "external import audit" in runtime_metadata["removal_condition"]

    assert coordinator_metadata["import_path"] == "app.services.chat.runtime.execution_coordinator"
    assert coordinator_metadata["migration_targets"] == [
        "app.services.chat.harness.finalizer",
        "app.services.chat.harness.support",
    ]
    assert "external import audit" in coordinator_metadata["removal_condition"]


def test_chat_harness_compatibility_audit_doc_lists_shims_and_targets() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    audit_doc = repo_root / "docs" / "ai" / "tracking" / "tasks" / "chat-harness-compatibility-audit.md"
    content = audit_doc.read_text(encoding="utf-8")

    assert "app.services.chat.runtime.unified_chat_runtime.process_chat" in content
    assert "app.services.chat.runtime." + "execution_coordinator" in content
    assert "app.services.chat.harness.chat_harness.ChatHarness" in content
    assert "app.services.chat.harness.dependencies.build_default_harness_dependencies" in content
    assert "runtime.unified_chat_runtime." + "build_understanding_result" in content


@pytest.mark.asyncio
async def test_unified_chat_runtime_delegates_to_chat_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    request = ChatRequest(user_id="compat-user", message="hello", locale="en-US")
    response = SimpleNamespace(marker="response")
    dependencies = SimpleNamespace(marker="dependencies")
    calls: list[dict[str, object]] = []

    class FakeHarness:
        def __init__(self, *, service, channel, dependencies):
            calls.append(
                {
                    "service": service,
                    "channel": channel,
                    "dependencies": dependencies,
                }
            )

        async def run(self, request):
            calls.append({"request": request})
            return SimpleNamespace(response=response)

    monkeypatch.setattr(unified_chat_runtime, "ChatHarness", FakeHarness)
    monkeypatch.setattr(unified_chat_runtime, "build_default_harness_dependencies", lambda: dependencies)

    service = SimpleNamespace(marker="service")
    result = await unified_chat_runtime.process_chat(service, request, channel="qa_console")

    assert result is response
    assert calls[0] == {
        "service": service,
        "channel": "qa_console",
        "dependencies": dependencies,
    }
    assert calls[1] == {"request": request}


@pytest.mark.asyncio
async def test_chat_service_process_chat_keeps_unified_runtime_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = ChatRequest(user_id="compat-user", message="hello", locale="en-US")
    response = SimpleNamespace(marker="response")
    calls: list[dict[str, object]] = []

    async def fake_process_chat(service, req: ChatRequest, channel: str | None = None) -> ChatResponse:
        calls.append({"service": service, "request": req, "channel": channel})
        return response

    monkeypatch.setattr("app.services.chat.service.unified_chat_runtime.process_chat", fake_process_chat)

    service = ChatService(db=object())
    result = await service.process_chat(request, channel="widget")

    assert result is response
    assert calls == [{"service": service, "request": request, "channel": "widget"}]
