from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.chat import ChatComponent, ChatResponse, ChatResponseMeta
from app.services.ai.llm_service import llm_service
from app.services.chat.components.pipeline import ComponentPipelineResult
from app.services.chat.service import ChatService


class DummyUser:
    id = "user-1"
    customer_name = None
    email = None


class DummyConversation:
    def __init__(self, conversation_id: int = 42, state: Any = None) -> None:
        self.id = conversation_id
        self.state = state


class RedisStub:
    async def get_json(self, key: str) -> None:
        return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int = 0) -> None:
        return None


class KnowledgeStub:
    async def search(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


def patch_llm_tracking(monkeypatch: Any) -> None:
    monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
    monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})


def patch_chat_service_lifecycle(
    monkeypatch: Any,
    *,
    conversation: DummyConversation | None = None,
    finalize_response: Callable[..., Awaitable[Any]] | None = None,
) -> None:
    async def fake_get_or_create_user(self, user_id: str, name: str | None = None, email: str | None = None):
        return DummyUser()

    async def fake_get_or_create_conversation(self, user: DummyUser, conversation_id: int | None):
        return conversation or DummyConversation()

    async def default_finalize_response(self, *, response: ChatResponse, **kwargs: Any) -> ChatResponse:
        return response

    monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(
        ChatService,
        "_finalize_response",
        finalize_response or default_finalize_response,
    )
    patch_llm_tracking(monkeypatch)


def build_component_pipeline_result(
    *,
    request: Any,
    conversation_id: int,
    reply_text: str,
    component_text: str | None = None,
    response_intent: str = "browse_products",
    source: str = "sql",
    debug: dict[str, Any] | None = None,
    response_debug: dict[str, Any] | None = None,
    conversation_state: dict[str, Any] | None = None,
) -> ComponentPipelineResult:
    pipeline_debug = {
        "component_plan": ["query_summary"],
        "component_source": source,
    }
    if debug:
        pipeline_debug.update(debug)

    return ComponentPipelineResult(
        response=ChatResponse(
            conversation_id=conversation_id,
            reply_text=reply_text,
            carousel_msg="",
            product_carousel=[],
            follow_up_questions=[],
            intent=response_intent,
            sources=[],
            debug=response_debug or {},
            components=[ChatComponent(type="query_summary", data={"text": component_text or reply_text})],
            meta=ChatResponseMeta(
                query_summary=request.message,
                latency_ms=1.0,
                source=source,
                llm_calls=0,
                embedding_calls=0,
            ),
        ),
        detail_mode_triggered=False,
        llm_calls=0,
        embedding_calls=0,
        external_call_counts={},
        spans={"response_build_ms": 1.0},
        debug=pipeline_debug,
        conversation_state=conversation_state,
    )
