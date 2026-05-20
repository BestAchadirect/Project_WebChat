from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatRequest
from app.services.chat.service import ChatService


@pytest.mark.asyncio
async def test_chat_service_process_chat_delegates_directly_to_chat_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = ChatRequest(user_id="harness-entrypoint-user", message="hello", locale="en-US")
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

    monkeypatch.setattr("app.services.chat.service.ChatHarness", FakeHarness)
    monkeypatch.setattr(
        "app.services.chat.service.build_default_harness_dependencies",
        lambda: dependencies,
    )

    service = ChatService(db=object())
    result = await service.process_chat(request, channel="qa_console")

    assert result is response
    assert calls == [
        {
            "service": service,
            "channel": "qa_console",
            "dependencies": dependencies,
        },
        {"request": request},
    ]
