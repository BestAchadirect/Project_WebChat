from __future__ import annotations

from typing import Any

from app.core.config import settings


def build_initial_debug_meta(*, channel: str, config_fingerprint: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": "",
        "workflow_path": "component_primary",
        "channel": channel,
        "config_fingerprint": config_fingerprint,
        "openai_timeout_seconds": float(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 12.0)),
        "openai_max_retries": int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
        "component_mode": "primary",
        "component_channel_allowed": True,
    }


def safe_conversation_id(conv: Any, fallback: int = 0) -> int:
    try:
        return int(getattr(conv, "id", 0) or 0)
    except Exception:
        return int(fallback or 0)
