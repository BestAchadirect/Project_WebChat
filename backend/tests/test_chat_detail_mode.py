from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse, ProductCard
from app.services.ai.llm_service import llm_service
from app.services.chat.service import ChatService


class _DummyUser:
    id = "user-1"
    customer_name = None
    email = None


class _DummyConversation:
    id = 9


def _card(
    *,
    sku: str,
    name: str,
    price: float = 1.0,
    stock_status: str = "in_stock",
    image_url: str | None = None,
    attributes: dict | None = None,
) -> ProductCard:
    return ProductCard(
        id=uuid4(),
        object_id=sku,
        sku=sku,
        name=name,
        price=price,
        currency="USD",
        stock_status=stock_status,
        image_url=image_url,
        product_url=None,
        attributes=attributes or {},
    )


@pytest.mark.asyncio
async def test_process_chat_detail_mode_price_stock(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.chat import service as chat_service_module

    monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_DETAIL_ENABLE_SEMANTIC_CACHE", False)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def fake_get_history(self, conversation_id, limit=5):
        return []

    async def fake_run_nlu(self, **kwargs):
        return {
            "intent": "knowledge_query",
            "show_products": False,
            "product_code": "",
            "refined_query": "barbell black 25mm",
            "requested_fields": ["price", "stock"],
            "attribute_filters": {"jewelry_type": "barbell", "color": "black", "gauge": "25mm"},
            "wants_image": False,
        }

    async def fake_resolve_language(self, **kwargs):
        return "en-US"

    async def fake_resolve_currency(self, **kwargs):
        return "USD"

    async def fake_smart_search(self, **kwargs):
        card = _card(
            sku="BB-25-BLK",
            name="Black Barbell 25mm",
            price=1.59,
            stock_status="in_stock",
            image_url=None,
            attributes={"jewelry_type": "Barbell", "color": "Black", "gauge": "25mm"},
        )
        return [card], [0.03], 0.03, {str(card.id): 0.03}

    async def fake_render(**kwargs):
        return ChatResponse(
            conversation_id=kwargs["conversation_id"],
            reply_text=kwargs["reply_data"]["reply"],
            carousel_msg=kwargs["reply_data"].get("carousel_hint"),
            product_carousel=kwargs["product_carousel"],
            follow_up_questions=kwargs["follow_up_questions"],
            intent=kwargs["route"],
            sources=kwargs["sources"],
            debug=kwargs["debug"],
        )

    async def fake_finalize_response(self, *, conversation_id, user_text, response, token_usage=None, channel=None):
        return response

    async def should_not_be_called(*args, **kwargs):
        raise AssertionError("semantic cache path should be skipped for detail mode")

    async def fake_generate_embedding(*args, **kwargs):
        return [0.0, 0.1]

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "get_history", fake_get_history)
    monkeypatch.setattr(ChatService, "_run_nlu", fake_run_nlu)
    monkeypatch.setattr(ChatService, "_resolve_reply_language", fake_resolve_language)
    monkeypatch.setattr(ChatService, "_resolve_target_currency", fake_resolve_currency)
    monkeypatch.setattr(ChatService, "smart_product_search", fake_smart_search)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(chat_service_module.semantic_cache_service, "get_hit", should_not_be_called)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    service = ChatService(db=object())
    monkeypatch.setattr(service._response_renderer, "render", fake_render)

    response = await service.process_chat(
        ChatRequest(user_id="guest-1", message="price and stock for black barbell 25mm"),
        channel="widget",
    )

    assert response.intent == "detail_mode"
    assert "Price:" in response.reply_text
    assert "Stock:" in response.reply_text
    assert response.product_carousel == []
    assert response.debug.get("detail_mode_enabled") is True
    assert response.debug.get("detail_match_count") == 1


@pytest.mark.asyncio
async def test_feature_flag_off_uses_legacy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.chat import service as chat_service_module

    monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", False)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    monkeypatch.setattr(settings, "PRODUCT_DISTANCE_THRESHOLD", 0.35)

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def fake_get_history(self, conversation_id, limit=5):
        return []

    async def fake_run_nlu(self, **kwargs):
        return {
            "intent": "knowledge_query",
            "show_products": False,
            "product_code": "",
            "refined_query": "shipping policy",
            "requested_fields": ["price", "stock"],
            "attribute_filters": {"jewelry_type": "barbell"},
            "wants_image": False,
        }

    async def fake_resolve_language(self, **kwargs):
        return "en-US"

    async def fake_resolve_currency(self, **kwargs):
        return "USD"

    async def fake_knowledge_sources(**kwargs):
        return [], {}

    async def fake_synthesize(self, **kwargs):
        return {"reply": "legacy response", "carousel_hint": "", "recommended_questions": []}

    async def fake_render(**kwargs):
        return ChatResponse(
            conversation_id=kwargs["conversation_id"],
            reply_text=kwargs["reply_data"]["reply"],
            carousel_msg=kwargs["reply_data"].get("carousel_hint"),
            product_carousel=kwargs["product_carousel"],
            follow_up_questions=kwargs["follow_up_questions"],
            intent=kwargs["route"],
            sources=kwargs["sources"],
            debug=kwargs["debug"],
        )

    async def fake_finalize_response(self, *, conversation_id, user_text, response, token_usage=None, channel=None):
        return response

    async def fake_get_hit(*args, **kwargs):
        return None

    async def fake_generate_embedding(*args, **kwargs):
        return [0.0, 0.1]

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "get_history", fake_get_history)
    monkeypatch.setattr(ChatService, "_run_nlu", fake_run_nlu)
    monkeypatch.setattr(ChatService, "_resolve_reply_language", fake_resolve_language)
    monkeypatch.setattr(ChatService, "_resolve_target_currency", fake_resolve_currency)
    monkeypatch.setattr(ChatService, "synthesize_answer", fake_synthesize)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(chat_service_module.semantic_cache_service, "get_hit", fake_get_hit)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    service = ChatService(db=object())
    monkeypatch.setattr(service._knowledge_context, "fetch_sources", fake_knowledge_sources)
    monkeypatch.setattr(service._response_renderer, "render", fake_render)

    response = await service.process_chat(
        ChatRequest(user_id="guest-1", message="shipping policy"),
        channel="widget",
    )

    assert response.intent == "rag_strict"
    assert response.reply_text == "legacy response"
    assert response.debug.get("detail_mode_enabled") is False
