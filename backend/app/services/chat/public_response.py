from __future__ import annotations

from typing import Any, Dict

from app.core.config import settings
from app.schemas.chat import ChatResponse


def _compact_agentic_debug(agentic: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key in ("selected", "used_tools", "fallback_to_component"):
        if key in agentic:
            compact[key] = bool(agentic.get(key))
    fallback_reason = str(agentic.get("fallback_reason") or "").strip()
    if fallback_reason:
        compact["fallback_reason"] = fallback_reason
    return compact


def compact_debug_payload(debug: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(debug or {})
    if not raw:
        return {}

    latency = raw.get("latency_spans") if isinstance(raw.get("latency_spans"), dict) else {}
    agentic = raw.get("agentic") if isinstance(raw.get("agentic"), dict) else {}
    compact: Dict[str, Any] = {}

    for key in (
        "run_id",
        "workflow",
        "workflow_path",
        "execution_mode",
        "component_mode",
        "clarify_reason",
        "tone_style",
        "tone_key",
        "tone_variant_id",
        "tone_anti_repeat_applied",
    ):
        value = raw.get(key)
        if isinstance(value, str):
            value = value.strip()
        if value not in ("", None):
            compact[key] = value

    source = str(raw.get("component_source") or raw.get("workflow_source") or "").strip()
    if source:
        compact["source"] = source

    if "total_ms" in latency:
        try:
            compact["latency_ms"] = round(float(latency.get("total_ms") or 0.0), 2)
        except Exception:
            pass

    compact_agentic = _compact_agentic_debug(agentic)
    if compact_agentic:
        compact["agentic"] = compact_agentic

    return compact


def prepare_public_chat_response(response: ChatResponse) -> ChatResponse:
    if bool(getattr(settings, "CHAT_PUBLIC_DEBUG_ENABLED", False)):
        return response
    response.debug = compact_debug_payload(getattr(response, "debug", {}) or {})
    return response
