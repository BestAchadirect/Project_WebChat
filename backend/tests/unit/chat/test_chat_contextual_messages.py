from __future__ import annotations

import pytest

from app.prompts import component_prompts
from app.services.chat.components.builders import contextual_messages
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.ai.llm_service import llm_service
from app.core.config import settings


@pytest.mark.parametrize(
    ("builder", "reply_language", "expected_terms"),
    [
        (component_prompts.contextual_clarify_prompt, "en-US", ["clarification message", "strict JSON", "message"]),
        (component_prompts.contextual_error_prompt, "en-US", ["recovery message", "strict JSON", "message"]),
        (component_prompts.contextual_product_prompt, "th-TH", ["product match reply", "strict JSON", "reply"]),
        (component_prompts.contextual_default_reply_prompt, "en-US", ["assistant reply", "strict JSON", "reply"]),
        (component_prompts.terminal_off_topic_prompt, "en-US", ["off-topic request", "strict JSON", "reply"]),
    ],
)
def test_contextual_prompt_builders_include_contract_terms(builder, reply_language, expected_terms) -> None:
    prompt = builder(reply_language)
    lowered = prompt.lower()
    assert reply_language in prompt
    for term in expected_terms:
        assert term.lower() in lowered


@pytest.mark.asyncio
async def test_generate_contextual_reply_uses_structured_payload_for_product_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_generate_chat_json(*, messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return {"reply": "  Titanium labrets are a lightweight fit.  "}

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    reply = await contextual_messages.generate_contextual_reply(
        kind="product",
        reply_language="en-US",
        payload={
            "user_text": "show titanium labrets",
            "focus_label": "titanium labret options",
            "benefit_text": "lightweight and skin-friendly",
            "products": [{"sku": "TI-1", "title": "Titanium Labret"}],
        },
    )

    assert reply == "Titanium labrets are a lightweight fit."
    messages = list(captured["messages"] or [])
    assert "product match reply" in str(messages[0]["content"]).lower()
    assert "titanium labret options" in str(messages[1]["content"]).lower()
    assert captured["kwargs"]["usage_kind"] == "chat_component_product_copy"


@pytest.mark.asyncio
async def test_generate_contextual_reply_rejects_empty_or_failed_llm_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_chat_json(*args, **kwargs):
        return {"reply": ""}

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    reply = await contextual_messages.generate_contextual_reply(
        kind="default",
        reply_language="en-US",
        payload={"user_text": "hello"},
    )

    assert reply == ""

    async def broken_generate_chat_json(*args, **kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(llm_service, "generate_chat_json", broken_generate_chat_json)

    reply = await contextual_messages.generate_contextual_reply(
        kind="off_topic",
        reply_language="en-US",
        payload={"user_text": "book a flight"},
    )

    assert reply == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected_phrase", "expected_usage_kind", "expected_reply"),
    [
        ("off_topic", "off-topic request", "chat_component_off_topic_copy", "I can help with body jewelry."),
    ],
)
async def test_generate_contextual_reply_handles_terminal_variants(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    expected_phrase: str,
    expected_usage_kind: str,
    expected_reply: str,
) -> None:
    captured: dict[str, object] = {}

    async def fake_generate_chat_json(*, messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return {"reply": expected_reply}

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    reply = await contextual_messages.generate_contextual_reply(
        kind=kind,
        reply_language="en-US",
        payload={"user_text": "hello"},
    )

    assert reply == expected_reply
    assert expected_phrase in str(captured["messages"][0]["content"]).lower()
    assert captured["kwargs"]["usage_kind"] == expected_usage_kind


@pytest.mark.asyncio
async def test_generate_contextual_component_message_uses_clarify_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_generate_chat_json(*, messages, **kwargs):
        captured["messages"] = messages
        return {"message": "Which size are you looking for?"}

    context = ComponentContext(
        user_text="show me the right size",
        locale="en-US",
        workflow="catalog",
        query_summary="show me the right size",
        source=ComponentSource.SQL,
        selected_components=[ComponentType.CLARIFY],
        debug={
            "clarify_reason": "fallback_uncertain",
            "clarify_questions": ["Which size are you looking for?"],
            "clarify_suggestions": ["Show 14g jewelry"],
        },
    )

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    message = await contextual_messages.generate_contextual_component_message(
        kind="clarify",
        context=context,
    )

    assert message == "Which size are you looking for?"
    assert "clarification message" in str(captured["messages"][0]["content"]).lower()
    assert "fallback_uncertain" in str(captured["messages"][1]["content"]).lower()
