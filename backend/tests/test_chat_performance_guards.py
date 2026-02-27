from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse, KnowledgeSource
from app.services.ai.llm_service import llm_service
from app.services.chat.hot_cache import hot_response_cache
from app.services.chat.product_detail_resolver import ProductDetailResolver
from app.services.chat.service import ChatService


class _DummyUser:
    id = "user-1"
    customer_name = None
    email = None


class _DummyConversation:
    id = 77


def _card(*, sku: str, material: str):
    return {
        "id": uuid4(),
        "object_id": sku,
        "sku": sku,
        "name": sku,
        "price": 1.0,
        "currency": "USD",
        "stock_status": "in_stock",
        "attributes": {"material": material},
    }


def test_detail_filtering_is_deterministic_without_llm() -> None:
    from app.schemas.chat import ProductCard

    steel = ProductCard(**_card(sku="ST-1", material="Steel"))
    titanium = ProductCard(**_card(sku="TI-1", material="Titanium"))
    resolution = ProductDetailResolver.resolve_detail_request(
        candidate_cards=[steel, titanium],
        distance_by_id={str(steel.id): 0.2, str(titanium.id): 0.1},
        requested_fields=["attributes"],
        attribute_filters={"material": "steel"},
        sku_token=None,
        nlu_product_code=None,
        max_matches=3,
        min_confidence=0.55,
    )
    assert [item.sku for item in resolution.matches] == ["ST-1"]


@pytest.mark.asyncio
async def test_hot_cache_hit_skips_history_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_HOT_CACHE_ENABLED", True)

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def should_not_load_history(self, conversation_id, limit=8):
        raise AssertionError("history load should be skipped on hot-cache hit")

    async def fake_finalize_response(self, *, conversation_id, user_text, response, token_usage=None, channel=None):
        return response

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "get_history", should_not_load_history)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})

    service = ChatService(db=object())
    key, _fp = service._build_hot_cache_lookup_key(
        text="show me steel labret options",
        locale="en-US",
        currency="USD",
        channel="widget",
    )
    hot_response_cache.set(
        key,
        {
            "reply_text": "Cached result",
            "carousel_msg": "",
            "product_carousel": [],
            "follow_up_questions": [],
            "intent": "rag_strict",
            "sources": [],
            "view_button_text": "View Product Details",
            "material_label": "Material",
            "jewelry_type_label": "Jewelry Type",
        },
    )

    response = await service.process_chat(
        ChatRequest(user_id="guest-cache", message="show me steel labret options", locale="en-US"),
        channel="widget",
    )

    assert response.reply_text == "Cached result"
    assert response.debug.get("hot_cache_hit") is True


@pytest.mark.asyncio
async def test_external_budget_exceeded_has_machine_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_HOT_CACHE_ENABLED", False)
    monkeypatch.setattr(settings, "NLU_FAST_PATH_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_EXTERNAL_CALL_BUDGET", 1)
    monkeypatch.setattr(settings, "CHAT_FAIL_FAST_ON_EMBEDDING_ERROR", True)

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def fake_get_history(self, conversation_id, limit=8):
        return []

    async def fake_finalize_response(self, *, conversation_id, user_text, response, token_usage=None, channel=None):
        return response

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

    async def fake_run_nlu(**kwargs):
        return {
            "intent": "knowledge_query",
            "show_products": False,
            "product_code": "",
            "refined_query": "shipping policy",
            "requested_fields": [],
            "attribute_filters": {},
            "wants_image": False,
        }

    async def should_not_call_embedding(*args, **kwargs):
        raise AssertionError("embedding should be blocked by external call budget")

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "get_history", fake_get_history)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})
    monkeypatch.setattr(llm_service, "run_nlu", fake_run_nlu)
    monkeypatch.setattr(llm_service, "generate_embedding", should_not_call_embedding)

    service = ChatService(db=object())
    monkeypatch.setattr(service._response_renderer, "render", fake_render)

    response = await service.process_chat(
        ChatRequest(user_id="guest-budget", message="what is your shipping policy", locale="en-US"),
        channel="widget",
    )

    assert response.intent == "fallback_general"
    assert response.debug.get("external_call_budget_exceeded_reason") == "external_call_budget"


@pytest.mark.asyncio
async def test_llm_render_guard_and_external_call_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.chat import service as chat_service_module

    monkeypatch.setattr(settings, "CHAT_HOT_CACHE_ENABLED", False)
    monkeypatch.setattr(settings, "NLU_FAST_PATH_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_EXTERNAL_CALL_BUDGET", 5)
    monkeypatch.setattr(settings, "CHAT_LLM_RENDER_ONLY_GUARD", True)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def fake_get_history(self, conversation_id, limit=8):
        return []

    async def fake_finalize_response(self, *, conversation_id, user_text, response, token_usage=None, channel=None):
        return response

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

    async def fake_run_nlu(**kwargs):
        return {
            "intent": "knowledge_query",
            "show_products": False,
            "product_code": "",
            "refined_query": "shipping policy",
            "requested_fields": [],
            "attribute_filters": {},
            "wants_image": False,
        }

    async def fake_generate_embedding(*args, **kwargs):
        return [0.01, 0.02]

    async def fake_get_hit(*args, **kwargs):
        return None

    async def fake_fetch_sources(**kwargs):
        return [
            KnowledgeSource(
                source_id="k1",
                title="Policy",
                content_snippet="Shipping policy",
                relevance=0.9,
            )
        ], {}

    async def fake_synthesize(self, **kwargs):
        return {"reply": "Policy response", "carousel_hint": "", "recommended_questions": []}

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "get_history", fake_get_history)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(ChatService, "synthesize_answer", fake_synthesize)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})
    monkeypatch.setattr(llm_service, "run_nlu", fake_run_nlu)
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(chat_service_module.semantic_cache_service, "get_hit", fake_get_hit)

    service = ChatService(db=object())
    monkeypatch.setattr(service._response_renderer, "render", fake_render)
    monkeypatch.setattr(service._knowledge_context, "fetch_sources", fake_fetch_sources)

    response = await service.process_chat(
        ChatRequest(user_id="guest-guard", message="shipping policy", locale="en-US"),
        channel="widget",
    )

    assert response.intent == "rag_strict"
    assert response.debug.get("llm_render_only_guard") is True
    external_counts = response.debug.get("external_call_counts") or {}
    assert int(external_counts.get("embedding_query", 0)) >= 1
    assert int(external_counts.get("llm_answer", 0)) >= 1


@pytest.mark.asyncio
async def test_hard_llm_call_cap_forces_deterministic_nlu_for_product(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.chat import service as chat_service_module

    monkeypatch.setattr(settings, "CHAT_HOT_CACHE_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 1)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_SQL_FIRST_ENABLED", False)

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def fake_get_history(self, conversation_id, limit=8):
        return []

    async def fake_finalize_response(self, *, conversation_id, user_text, response, token_usage=None, channel=None):
        return response

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

    async def should_not_call_run_nlu(**kwargs):
        raise AssertionError("LLM NLU should be skipped when hard cap is enabled")

    async def fake_generate_embedding(*args, **kwargs):
        return [0.01, 0.02]

    async def fake_get_hit(*args, **kwargs):
        return None

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "get_history", fake_get_history)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})
    monkeypatch.setattr(llm_service, "run_nlu", should_not_call_run_nlu)
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(chat_service_module.semantic_cache_service, "get_hit", fake_get_hit)

    service = ChatService(db=object())
    monkeypatch.setattr(service._response_renderer, "render", fake_render)

    response = await service.process_chat(
        ChatRequest(user_id="guest-cap", message="show titanium barbell options", locale="en-US"),
        channel="widget",
    )

    assert response.debug.get("nlu_fast_path_forced_by_llm_cap") is True
    assert int(response.debug.get("llm_call_count") or 0) == 0
