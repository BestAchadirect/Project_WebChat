from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse, ChatRouting
from app.services.chat import persistence
from app.services.chat.service import ChatService
from tests.fixtures.chat import (
    DummyConversation,
    build_component_pipeline_result,
    patch_chat_service_lifecycle,
)
from tests.fixtures.persistence import PersistenceDB, RuntimeDB


@pytest.fixture(autouse=True)
def chat_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_SQL_FIRST_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False)


@pytest.mark.asyncio
async def test_process_chat_component_primary_forwards_conversation_state(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    state_payload = {
        "version": 1,
        "last_workflow": "catalog",
        "last_refined_query": "cheaper ones",
        "last_attribute_filters": {"material": "titanium"},
        "last_requested_fields": [],
        "last_product_ids": ["p-1"],
        "last_currency": "USD",
        "last_route": "catalog",
        "updated_at": "2026-03-10T00:00:00Z",
    }

    async def fake_finalize_response(
        self,
        *,
        response,
        conversation_state=None,
        **kwargs,
    ):
        captured["conversation_state"] = conversation_state
        return response

    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text="component response",
            debug={"conversation_state_enabled": True, "component_plan": ["query_summary"]},
            conversation_state=state_payload,
        )

    patch_chat_service_lifecycle(
        monkeypatch,
        conversation=DummyConversation(conversation_id=77, state=None),
        finalize_response=fake_finalize_response,
    )
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    service = ChatService(db=RuntimeDB())
    response = await service.process_chat(
        ChatRequest(user_id="guest-1", message="cheaper ones"),
        channel="widget",
    )

    assert response.reply_text == "component response"
    assert response.debug.get("component_mode") == "primary"
    assert captured["conversation_state"] == state_payload


@pytest.mark.asyncio
async def test_finalize_response_persists_conversation_state_when_provided() -> None:
    db = PersistenceDB()
    response = ChatResponse(
        conversation_id=1,
        reply_text="ok",
        carousel_msg="",
        product_carousel=[],
        follow_up_questions=[],
        routing=ChatRouting(workflow="fallback", execution_mode="component", needs_clarification=True),
        sources=[],
        debug={},
    )
    state_payload = {
        "version": 1,
        "last_workflow": "catalog",
        "last_refined_query": "titanium belly rings",
        "last_attribute_filters": {"material": "titanium"},
        "last_requested_fields": [],
        "last_product_ids": [],
        "last_currency": "USD",
        "last_route": "catalog",
        "updated_at": "2026-03-09T00:00:00Z",
    }

    await persistence.finalize_response(
        db=db,
        conversation_id=1,
        user_text="show titanium belly rings",
        response=response,
        conversation_state=state_payload,
    )

    assert db.committed is True
    assistant_msg = db.added[1]
    assert assistant_msg.components[0]["type"] == "assistant_message"
    assert assistant_msg.components[0]["data"]["text"] == "ok"
    values = {
        getattr(key, "key", str(key)): value
        for key, value in dict(getattr(db.executed[-1], "_values", {})).items()
    }
    assert getattr(values["state"], "value", values["state"]) == state_payload
