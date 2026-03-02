from __future__ import annotations

import pytest

from app.core.config import settings
from uuid import uuid4

from app.schemas.chat import ChatComponent, ChatRequest, ChatResponse, ChatResponseMeta, ProductCard
from app.services.ai.llm_service import llm_service
from app.services.chat.components.pipeline import ComponentPipelineResult
from app.services.chat.service import ChatService


class _DummyUser:
    id = "user-1"
    customer_name = None
    email = None


class _DummyConversation:
    id = 42


@pytest.mark.asyncio
async def test_chat_service_component_mode_returns_component_pipeline_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED_CHANNELS", "widget")

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def fake_finalize_response(self, *, conversation_id, user_text, response, token_usage=None, channel=None):
        return response

    async def fake_component_pipeline(self, *, request, conversation_id, run_id):
        return ComponentPipelineResult(
            response=ChatResponse(
                conversation_id=conversation_id,
                reply_text="component response",
                carousel_msg="",
                product_carousel=[],
                follow_up_questions=[],
                intent="browse_products",
                sources=[],
                components=[ChatComponent(type="query_summary", data={"text": "component response"})],
                meta=ChatResponseMeta(
                    query_summary=request.message,
                    latency_ms=1.0,
                    source="sql",
                    llm_calls=0,
                    embedding_calls=0,
                ),
            ),
            detail_mode_triggered=False,
            llm_calls=0,
            embedding_calls=0,
            external_call_counts={},
            spans={"response_build_ms": 1.0},
            debug={"component_plan": ["query_summary"], "component_source": "sql"},
        )

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-1", message="list steel rings", locale="en-US"),
        channel="widget",
    )

    assert response.reply_text == "component response"
    assert response.debug.get("component_mode") == "active"
    assert response.debug.get("component_plan") == ["query_summary"]


@pytest.mark.asyncio
async def test_chat_service_component_require_mode_returns_component_error_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", True)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED_CHANNELS", "widget")

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def fake_finalize_response(self, *, conversation_id, user_text, response, token_usage=None, channel=None):
        return response

    async def failing_component_pipeline(self, *, request, conversation_id, run_id):
        raise RuntimeError("pipeline failed")

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", failing_component_pipeline)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})

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
async def test_chat_service_component_mode_respects_enabled_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED_CHANNELS", "widget")

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def fake_finalize_response(self, *, conversation_id, user_text, response, token_usage=None, channel=None):
        return response

    async def should_not_run_component_pipeline(self, *, request, conversation_id, run_id):
        raise AssertionError("component pipeline should be disabled for non-widget channel")

    async def fake_precheck(self, *, user_text, limit=3, candidates=None):
        card = ProductCard(
            id=uuid4(),
            object_id="OBJ-1",
            sku="SKU-123",
            legacy_sku=[],
            name="SKU-123",
            description=None,
            price=10.0,
            currency="USD",
            stock_status="in_stock",
            image_url=None,
            product_url=None,
            attributes={},
        )
        return "sku-123", [card]

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", should_not_run_component_pipeline)
    monkeypatch.setattr(ChatService, "_cheap_sku_precheck", fake_precheck)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})

    service = ChatService(db=object())
    response = await service.process_chat(
        ChatRequest(user_id="guest-3", message="SKU-123", locale="en-US"),
        channel="qa_console",
    )

    assert response.debug.get("component_channel_allowed") is False
    assert response.debug.get("component_mode") == "disabled_for_channel"
    assert response.debug.get("sku_precheck_hit") is True
