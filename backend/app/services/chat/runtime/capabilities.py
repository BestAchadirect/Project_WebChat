from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from app.core.config import settings


@dataclass(frozen=True)
class ChatRuntimeCapabilities:
    chat_semantic_first_enabled: bool
    chat_semantic_soft_filter_rerank_enabled: bool
    chat_semantic_min_acceptance_score: float
    chat_projection_dual_write_enabled: bool
    chat_structured_query_cache_enabled: bool
    chat_external_call_budget: int
    chat_external_call_retry_max: int
    chat_external_call_fail_fast_seconds: float
    chat_vector_top_k: int
    chat_structured_candidate_cap: int
    chat_cross_sell_mode: str
    chat_max_history_tokens: int
    chat_hard_max_llm_calls_per_request: int
    chat_hard_max_embeddings_per_request: int
    chat_embedding_retry_max: int
    chat_strict_retrieval_separation_enabled: bool
    chat_component_buckets_enabled: bool
    chat_component_buckets_shadow_mode: bool
    chat_component_buckets_require_components: bool
    chat_component_buckets_enabled_channels: str
    chat_conversation_state_enabled: bool
    chat_tone_humanizer_enabled: bool
    chat_tone_anti_repeat_window: int
    chat_tone_max_sentences: int
    chat_tone_max_chars: int
    chat_tone_enabled_channels: str
    chat_catalog_version: str
    chat_prompt_version: str
    chat_llm_routing_enabled: bool
    chat_llm_routing_model: str
    chat_llm_routing_max_tokens: int
    chat_llm_routing_temperature: float
    chat_llm_routing_timeout_ms: int
    chat_llm_routing_timeout_retry_enabled: bool
    chat_llm_routing_timeout_retry_ms: int
    chat_llm_routing_min_confidence: float
    chat_agentic_min_confidence: float
    chat_clarify_guardrails_enabled: bool
    chat_knowledge_min_relevance: float
    chat_knowledge_high_risk_guard_enabled: bool
    chat_conversion_follow_ups_enabled: bool
    chat_product_click_tracking_enabled: bool
    openai_timeout_seconds: float
    openai_max_retries: int
    agentic_function_calling_enabled: bool
    agentic_allowed_channels: str
    agentic_enable_fallback: bool
    chat_cache_log_interval_seconds: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chat_semantic_first_enabled": self.chat_semantic_first_enabled,
            "chat_semantic_soft_filter_rerank_enabled": self.chat_semantic_soft_filter_rerank_enabled,
            "chat_semantic_min_acceptance_score": self.chat_semantic_min_acceptance_score,
            "chat_projection_dual_write_enabled": self.chat_projection_dual_write_enabled,
            "chat_structured_query_cache_enabled": self.chat_structured_query_cache_enabled,
            "chat_external_call_budget": self.chat_external_call_budget,
            "chat_external_call_retry_max": self.chat_external_call_retry_max,
            "chat_external_call_fail_fast_seconds": self.chat_external_call_fail_fast_seconds,
            "chat_vector_top_k": self.chat_vector_top_k,
            "chat_structured_candidate_cap": self.chat_structured_candidate_cap,
            "chat_cross_sell_mode": self.chat_cross_sell_mode,
            "chat_max_history_tokens": self.chat_max_history_tokens,
            "chat_hard_max_llm_calls_per_request": self.chat_hard_max_llm_calls_per_request,
            "chat_hard_max_embeddings_per_request": self.chat_hard_max_embeddings_per_request,
            "chat_embedding_retry_max": self.chat_embedding_retry_max,
            "chat_strict_retrieval_separation_enabled": self.chat_strict_retrieval_separation_enabled,
            "chat_component_buckets_enabled": self.chat_component_buckets_enabled,
            "chat_component_buckets_shadow_mode": self.chat_component_buckets_shadow_mode,
            "chat_component_buckets_require_components": self.chat_component_buckets_require_components,
            "chat_component_buckets_enabled_channels": self.chat_component_buckets_enabled_channels,
            "chat_conversation_state_enabled": self.chat_conversation_state_enabled,
            "chat_tone_humanizer_enabled": self.chat_tone_humanizer_enabled,
            "chat_tone_anti_repeat_window": self.chat_tone_anti_repeat_window,
            "chat_tone_max_sentences": self.chat_tone_max_sentences,
            "chat_tone_max_chars": self.chat_tone_max_chars,
            "chat_tone_enabled_channels": self.chat_tone_enabled_channels,
            "chat_catalog_version": self.chat_catalog_version,
            "chat_prompt_version": self.chat_prompt_version,
            "chat_llm_routing_enabled": self.chat_llm_routing_enabled,
            "chat_llm_routing_model": self.chat_llm_routing_model,
            "chat_llm_routing_max_tokens": self.chat_llm_routing_max_tokens,
            "chat_llm_routing_temperature": self.chat_llm_routing_temperature,
            "chat_llm_routing_timeout_ms": self.chat_llm_routing_timeout_ms,
            "chat_llm_routing_timeout_retry_enabled": self.chat_llm_routing_timeout_retry_enabled,
            "chat_llm_routing_timeout_retry_ms": self.chat_llm_routing_timeout_retry_ms,
            "chat_llm_routing_min_confidence": self.chat_llm_routing_min_confidence,
            "chat_agentic_min_confidence": self.chat_agentic_min_confidence,
            "chat_clarify_guardrails_enabled": self.chat_clarify_guardrails_enabled,
            "chat_knowledge_min_relevance": self.chat_knowledge_min_relevance,
            "chat_knowledge_high_risk_guard_enabled": self.chat_knowledge_high_risk_guard_enabled,
            "chat_conversion_follow_ups_enabled": self.chat_conversion_follow_ups_enabled,
            "chat_product_click_tracking_enabled": self.chat_product_click_tracking_enabled,
            "openai_timeout_seconds": self.openai_timeout_seconds,
            "openai_max_retries": self.openai_max_retries,
            "agentic_function_calling_enabled": self.agentic_function_calling_enabled,
            "agentic_allowed_channels": self.agentic_allowed_channels,
            "agentic_enable_fallback": self.agentic_enable_fallback,
            "chat_cache_log_interval_seconds": self.chat_cache_log_interval_seconds,
        }

    def is_agentic_channel_enabled(self, *, channel: str | None) -> bool:
        if not self.agentic_function_calling_enabled:
            return False
        allowed = {part.strip().lower() for part in str(self.agentic_allowed_channels or "").split(",") if part.strip()}
        if not allowed:
            return True
        return str(channel or "").strip().lower() in allowed

    def is_tone_channel_allowed(self, *, channel: str | None) -> bool:
        allowed = {part.strip().lower() for part in str(self.chat_tone_enabled_channels or "").split(",") if part.strip()}
        return not allowed or str(channel or "widget").strip().lower() in allowed


def build_chat_runtime_capabilities() -> ChatRuntimeCapabilities:
    return ChatRuntimeCapabilities(
        chat_semantic_first_enabled=bool(getattr(settings, "CHAT_SEMANTIC_FIRST_ENABLED", True)),
        chat_semantic_soft_filter_rerank_enabled=bool(
            getattr(settings, "CHAT_SEMANTIC_SOFT_FILTER_RERANK_ENABLED", True)
        ),
        chat_semantic_min_acceptance_score=float(getattr(settings, "CHAT_SEMANTIC_MIN_ACCEPTANCE_SCORE", 0.35)),
        chat_projection_dual_write_enabled=bool(getattr(settings, "CHAT_PROJECTION_DUAL_WRITE_ENABLED", True)),
        chat_structured_query_cache_enabled=bool(getattr(settings, "CHAT_STRUCTURED_QUERY_CACHE_ENABLED", True)),
        chat_external_call_budget=int(getattr(settings, "CHAT_EXTERNAL_CALL_BUDGET", 3)),
        chat_external_call_retry_max=int(getattr(settings, "CHAT_EXTERNAL_CALL_RETRY_MAX", 1)),
        chat_external_call_fail_fast_seconds=float(getattr(settings, "CHAT_EXTERNAL_CALL_FAIL_FAST_SECONDS", 3.5)),
        chat_vector_top_k=int(getattr(settings, "CHAT_VECTOR_TOP_K", 12)),
        chat_structured_candidate_cap=int(getattr(settings, "CHAT_STRUCTURED_CANDIDATE_CAP", 300)),
        chat_cross_sell_mode=str(getattr(settings, "CHAT_CROSS_SELL_MODE", "off")),
        chat_max_history_tokens=int(getattr(settings, "CHAT_MAX_HISTORY_TOKENS", 1200)),
        chat_hard_max_llm_calls_per_request=int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0)),
        chat_hard_max_embeddings_per_request=int(getattr(settings, "CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST", 1)),
        chat_embedding_retry_max=int(getattr(settings, "CHAT_EMBEDDING_RETRY_MAX", 1)),
        chat_strict_retrieval_separation_enabled=bool(
            getattr(settings, "CHAT_STRICT_RETRIEVAL_SEPARATION_ENABLED", False)
        ),
        chat_component_buckets_enabled=bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False)),
        chat_component_buckets_shadow_mode=bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)),
        chat_component_buckets_require_components=bool(
            getattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
        ),
        chat_component_buckets_enabled_channels=str(
            getattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED_CHANNELS", "widget")
        ),
        chat_conversation_state_enabled=bool(getattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False)),
        chat_tone_humanizer_enabled=bool(getattr(settings, "CHAT_TONE_HUMANIZER_ENABLED", True)),
        chat_tone_anti_repeat_window=int(getattr(settings, "CHAT_TONE_ANTI_REPEAT_WINDOW", 4)),
        chat_tone_max_sentences=int(getattr(settings, "CHAT_TONE_MAX_SENTENCES", 2)),
        chat_tone_max_chars=int(getattr(settings, "CHAT_TONE_MAX_CHARS", 220)),
        chat_tone_enabled_channels=str(getattr(settings, "CHAT_TONE_ENABLED_CHANNELS", "widget")),
        chat_catalog_version=str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
        chat_prompt_version=str(getattr(settings, "CHAT_PROMPT_VERSION", "v1")),
        chat_llm_routing_enabled=bool(getattr(settings, "CHAT_LLM_ROUTING_ENABLED", False)),
        chat_llm_routing_model=str(getattr(settings, "CHAT_LLM_ROUTING_MODEL", "")),
        chat_llm_routing_max_tokens=int(getattr(settings, "CHAT_LLM_ROUTING_MAX_TOKENS", 180)),
        chat_llm_routing_temperature=float(getattr(settings, "CHAT_LLM_ROUTING_TEMPERATURE", 0.0)),
        chat_llm_routing_timeout_ms=int(getattr(settings, "CHAT_LLM_ROUTING_TIMEOUT_MS", 5000)),
        chat_llm_routing_timeout_retry_enabled=bool(
            getattr(settings, "CHAT_LLM_ROUTING_TIMEOUT_RETRY_ENABLED", True)
        ),
        chat_llm_routing_timeout_retry_ms=int(getattr(settings, "CHAT_LLM_ROUTING_TIMEOUT_RETRY_MS", 2000)),
        chat_llm_routing_min_confidence=float(getattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7)),
        chat_agentic_min_confidence=float(getattr(settings, "CHAT_AGENTIC_MIN_CONFIDENCE", 0.8)),
        chat_clarify_guardrails_enabled=bool(getattr(settings, "CHAT_CLARIFY_GUARDRAILS_ENABLED", True)),
        chat_knowledge_min_relevance=float(getattr(settings, "CHAT_KNOWLEDGE_MIN_RELEVANCE", 0.55)),
        chat_knowledge_high_risk_guard_enabled=bool(
            getattr(settings, "CHAT_KNOWLEDGE_HIGH_RISK_GUARD_ENABLED", True)
        ),
        chat_conversion_follow_ups_enabled=bool(getattr(settings, "CHAT_CONVERSION_FOLLOW_UPS_ENABLED", True)),
        chat_product_click_tracking_enabled=bool(getattr(settings, "CHAT_PRODUCT_CLICK_TRACKING_ENABLED", True)),
        openai_timeout_seconds=float(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 12.0)),
        openai_max_retries=int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
        agentic_function_calling_enabled=bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)),
        agentic_allowed_channels=str(getattr(settings, "AGENTIC_ALLOWED_CHANNELS", "")),
        agentic_enable_fallback=bool(getattr(settings, "AGENTIC_ENABLE_FALLBACK", True)),
        chat_cache_log_interval_seconds=int(getattr(settings, "CHAT_CACHE_LOG_INTERVAL_SECONDS", 60)),
    )
