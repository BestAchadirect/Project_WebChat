from app.core.config import settings
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities


def test_build_chat_runtime_capabilities_reflects_updated_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CHAT_CACHE_LOG_INTERVAL_SECONDS", 17, raising=False)
    monkeypatch.setattr(settings, "CHAT_LLM_ROUTING_TEMPERATURE", 0.25, raising=False)
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AGENTIC_ALLOWED_CHANNELS", "widget, admin", raising=False)
    monkeypatch.setattr(settings, "CHAT_TONE_ENABLED_CHANNELS", "widget", raising=False)

    capabilities = build_chat_runtime_capabilities()

    assert capabilities.chat_cache_log_interval_seconds == 17
    assert capabilities.chat_llm_routing_temperature == 0.25
    assert capabilities.is_agentic_channel_enabled(channel="admin") is True
    assert capabilities.is_tone_channel_allowed(channel="widget") is True
