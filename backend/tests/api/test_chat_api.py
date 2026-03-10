from __future__ import annotations

import pytest

pytest.importorskip("pydantic_settings")

from app.api.routes.chat import router
from app.dependencies import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat.service import ChatService


async def override_get_db():
    return object()


def response_payload() -> ChatResponse:
    return ChatResponse(
        conversation_id=123,
        reply_text="api response",
        carousel_msg="",
        product_carousel=[],
        follow_up_questions=[],
        intent="browse_products",
        sources=[],
        debug={},
        components=[],
    )


def test_chat_endpoint_returns_service_response(build_client, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_process_chat(self, request: ChatRequest, channel: str | None = None) -> ChatResponse:
        captured["request"] = request
        captured["channel"] = channel
        return response_payload()

    monkeypatch.setattr(ChatService, "process_chat", fake_process_chat)
    client = build_client(
        router=router,
        prefix="/api/v1/chat",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.post(
        "/api/v1/chat/",
        json={"user_id": "guest-1", "message": "show steel rings", "locale": "en-US"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "reply_text" not in payload
    assert "product_carousel" not in payload
    assert "follow_up_questions" not in payload
    assert payload["components"][0]["type"] == "assistant_message"
    assert payload["components"][0]["data"]["text"] == "api response"
    assert captured["channel"] == "widget"
    assert isinstance(captured["request"], ChatRequest)


def test_chat_endpoint_rejects_invalid_request(build_client) -> None:
    client = build_client(
        router=router,
        prefix="/api/v1/chat",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.post("/api/v1/chat/", json={"message": "missing user id"})

    assert response.status_code == 422


def test_chat_endpoint_returns_500_when_service_raises(build_client, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_process_chat(self, request: ChatRequest, channel: str | None = None) -> ChatResponse:
        raise RuntimeError("chat exploded")

    monkeypatch.setattr(ChatService, "process_chat", failing_process_chat)
    client = build_client(
        router=router,
        prefix="/api/v1/chat",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.post(
        "/api/v1/chat/",
        json={"user_id": "guest-1", "message": "show steel rings", "locale": "en-US"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "chat exploded"}


def test_chat_history_returns_component_first_messages(build_client, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_user(self, user_id: str):
        return object()

    async def fake_get_conversation_for_user(self, user: object, conversation_id: int):
        return object()

    def fake_is_conversation_active(self, conversation: object) -> bool:
        return True

    async def fake_get_history(self, conversation_id: int, limit: int = 50):
        return [
            {"role": "user", "content": "show titanium labrets", "created_at": None},
            {
                "role": "assistant",
                "content": "I found a match.",
                "product_data": [
                    {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "object_id": "OBJ-1",
                        "sku": "SKU-1",
                        "legacy_sku": [],
                        "name": "Titanium Labret",
                        "description": "",
                        "price": 12.5,
                        "currency": "USD",
                        "stock_status": "in_stock",
                        "image_url": None,
                        "product_url": None,
                        "attributes": {"material": "Titanium"},
                    }
                ],
                "created_at": None,
            },
        ]

    monkeypatch.setattr(ChatService, "get_user", fake_get_user)
    monkeypatch.setattr(ChatService, "get_conversation_for_user", fake_get_conversation_for_user)
    monkeypatch.setattr(ChatService, "is_conversation_active", fake_is_conversation_active)
    monkeypatch.setattr(ChatService, "get_history", fake_get_history)

    client = build_client(
        router=router,
        prefix="/api/v1/chat",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.get(
        "/api/v1/chat/history/123",
        params={"user_id": "guest-1", "limit": 50},
    )

    assert response.status_code == 200
    payload = response.json()
    assistant_message = payload["messages"][1]
    assert "product_data" not in assistant_message
    assert assistant_message["components"][0]["type"] == "assistant_message"
    assert assistant_message["components"][0]["data"]["text"] == "I found a match."
    assert assistant_message["components"][1]["type"] == "product_cards"
