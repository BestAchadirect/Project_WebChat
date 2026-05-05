from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic_settings")

from app.services.ai.llm_service import llm_service


def _response_with_content(content: str, *, finish_reason: str = "stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]), finish_reason=finish_reason)],
        usage=None,
    )


class _RetryingCompletions:
    def __init__(self, response):
        self.calls = []
        self._response = response

    async def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        if len(self.calls) == 1:
            raise RuntimeError(
                "Unsupported parameter: 'max_tokens' is not supported with this model. "
                "Use 'max_completion_tokens' instead."
            )
        return self._response


class _SequenceCompletions:
    def __init__(self, responses_or_errors):
        self.calls = []
        self._responses_or_errors = list(responses_or_errors)

    async def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        item = self._responses_or_errors.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_generate_chat_json_retries_with_max_completion_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions = _RetryingCompletions(_response_with_content('{"reply":"ok"}'))
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(llm_service, "client", fake_client)

    result = await llm_service.generate_chat_json(
        messages=[{"role": "user", "content": "hello"}],
        model="test-model",
        max_tokens=123,
    )

    assert result == {"reply": "ok"}
    assert completions.calls[0]["max_tokens"] == 123
    assert "max_completion_tokens" not in completions.calls[0]
    assert completions.calls[1]["max_completion_tokens"] == 123
    assert "max_tokens" not in completions.calls[1]


@pytest.mark.asyncio
async def test_generate_chat_response_retries_with_max_completion_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions = _RetryingCompletions(_response_with_content("plain text response"))
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(llm_service, "client", fake_client)

    result = await llm_service.generate_chat_response(
        messages=[{"role": "user", "content": "hello"}],
        model="test-model",
        max_tokens=77,
    )

    assert result == "plain text response"
    assert completions.calls[1]["max_completion_tokens"] == 77


@pytest.mark.asyncio
async def test_generate_chat_json_retries_without_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions = _SequenceCompletions(
        [
            RuntimeError(
                "Unsupported value: 'temperature' does not support 0.2 with this model. "
                "Only the default (1) value is supported."
            ),
            _response_with_content('{"reply":"ok"}'),
        ]
    )
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(llm_service, "client", fake_client)

    result = await llm_service.generate_chat_json(
        messages=[{"role": "user", "content": "hello"}],
        model="test-model",
        temperature=0.2,
    )

    assert result == {"reply": "ok"}
    assert completions.calls[0]["temperature"] == 0.2
    assert "temperature" not in completions.calls[1]


@pytest.mark.asyncio
async def test_generate_chat_json_retries_for_max_tokens_then_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions = _SequenceCompletions(
        [
            RuntimeError(
                "Unsupported parameter: 'max_tokens' is not supported with this model. "
                "Use 'max_completion_tokens' instead."
            ),
            RuntimeError(
                "Unsupported value: 'temperature' does not support 0.2 with this model. "
                "Only the default (1) value is supported."
            ),
            _response_with_content('{"reply":"ok"}'),
        ]
    )
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(llm_service, "client", fake_client)

    result = await llm_service.generate_chat_json(
        messages=[{"role": "user", "content": "hello"}],
        model="test-model",
        temperature=0.2,
        max_tokens=123,
    )

    assert result == {"reply": "ok"}
    assert completions.calls[0]["max_tokens"] == 123
    assert "max_completion_tokens" not in completions.calls[0]
    assert completions.calls[1]["max_completion_tokens"] == 123
    assert completions.calls[1]["temperature"] == 0.2
    assert "temperature" not in completions.calls[2]


@pytest.mark.asyncio
async def test_generate_chat_json_uses_gpt5_compat_request_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions = _SequenceCompletions([_response_with_content('{"reply":"ok"}')])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(llm_service, "client", fake_client)

    result = await llm_service.generate_chat_json(
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-5-mini",
        temperature=0.0,
        max_tokens=123,
        reasoning_effort="minimal",
    )

    assert result == {"reply": "ok"}
    assert completions.calls[0]["max_completion_tokens"] == 123
    assert "max_tokens" not in completions.calls[0]
    assert "temperature" not in completions.calls[0]
    assert completions.calls[0]["reasoning_effort"] == "minimal"


@pytest.mark.asyncio
async def test_generate_chat_json_raises_on_empty_truncated_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions = _SequenceCompletions([_response_with_content("", finish_reason="length")])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(llm_service, "client", fake_client)

    with pytest.raises(RuntimeError, match="truncated before content"):
        await llm_service.generate_chat_json(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5-mini",
            max_tokens=123,
        )
