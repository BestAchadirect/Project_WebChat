from __future__ import annotations

from typing import Any, Dict

from app.core.config import settings
from app.schemas.chat import ChatResponse

_DEBUG_EXPORT_DROP_KEYS = {
    "component_pipeline_enabled",
    "path_kind",
    "workflow_needs_products",
    "workflow_needs_knowledge",
    "workflow_needs_clarification",
    "workflow_store_overview_request",
    "execution_mode",
    "llm_call_count",
    "embedding_count",
    "component_count",
    "external_call_retries_used",
}


def sanitize_debug_payload(debug: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(debug or {})
    if not raw:
        return {}
    for key in _DEBUG_EXPORT_DROP_KEYS:
        raw.pop(key, None)
    return raw


def prepare_public_chat_response(response: ChatResponse) -> ChatResponse:
    if bool(getattr(settings, "CHAT_PUBLIC_DEBUG_ENABLED", False)):
        return response
    response.debug = {}
    return response
