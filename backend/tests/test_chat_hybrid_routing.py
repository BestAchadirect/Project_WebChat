import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat.agentic.orchestrator import AgentRunResult
from app.services.chat.service import ChatService
from app.services.ai.llm_service import llm_service


class _DummyUser:
    id = "user-1"
    customer_name = None
    email = None


class _DummyConversation:
    id = 42


@pytest.mark.asyncio
async def test_process_chat_returns_agentic_response_and_skips_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.chat import service as chat_service_module

    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget,qa_console")
    monkeypatch.setattr(settings, "AGENTIC_ENABLE_FALLBACK", True)

    async def fake_get_or_create_user(self, user_id, name=None, email=None):
        return _DummyUser()

    async def fake_get_or_create_conversation(self, user, conversation_id):
        return _DummyConversation()

    async def fake_get_history(self, conversation_id, limit=5):
        return []

    async def fake_run_nlu(self, **kwargs):
        return {
            "intent": "search_specific",
            "show_products": True,
            "product_code": "ABC-1",
            "refined_query": "ABC-1",
        }

    async def fake_resolve_language(self, **kwargs):
        return "en-US"

    async def fake_resolve_currency(self, **kwargs):
        return "USD"

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

    class _FakeAgentOrchestrator:
        def __init__(self, *, db, run_id, channel):
            self.db = db
            self.run_id = run_id
            self.channel = channel

        async def run(self, *, user_text, history, reply_language):
            return AgentRunResult(
                final_reply="Agent tool response",
                used_tools=True,
                trace=[{"tool": "check_inventory_db", "status": "ok"}],
            )

    async def should_not_be_called(*args, **kwargs):
        raise AssertionError("semantic cache path should be skipped for tool-executed turns")

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(ChatService, "get_history", fake_get_history)
    monkeypatch.setattr(ChatService, "_run_nlu", fake_run_nlu)
    monkeypatch.setattr(ChatService, "_resolve_reply_language", fake_resolve_language)
    monkeypatch.setattr(ChatService, "_resolve_target_currency", fake_resolve_currency)
    monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
    monkeypatch.setattr(chat_service_module, "AgentOrchestrator", _FakeAgentOrchestrator)
    monkeypatch.setattr(chat_service_module.semantic_cache_service, "get_hit", should_not_be_called)
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})

    service = ChatService(db=object())
    monkeypatch.setattr(service._response_renderer, "render", fake_render)

    response = await service.process_chat(
        ChatRequest(user_id="guest-1", message="check ABC-1"),
        channel="widget",
    )

    assert response.reply_text == "Agent tool response"
    assert response.intent == "agentic_tools"
    assert response.debug.get("agentic", {}).get("used_tools") is True

