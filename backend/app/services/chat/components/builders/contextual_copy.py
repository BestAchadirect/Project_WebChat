from __future__ import annotations

import json
import logging
from typing import Any, Dict

from app.core.config import settings
from app.prompts.component_copy import contextual_clarify_prompt, contextual_error_prompt
from app.services.ai.llm_service import llm_service
from app.services.chat.components.context import ComponentContext

logger = logging.getLogger(__name__)


def _copy_model() -> str:
    return str(
        getattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_MODEL", "")
        or getattr(settings, "NLU_MODEL", "gpt-5-mini")
    ).strip()


def _reply_language(context: ComponentContext) -> str:
    return str(context.locale or getattr(settings, "DEFAULT_LOCALE", "en-US")).strip() or "en-US"


def _clarify_payload(context: ComponentContext) -> Dict[str, Any]:
    debug = dict(context.debug or {})
    return {
        "user_text": str(context.user_text or ""),
        "query_summary": str(context.query_summary or ""),
        "workflow": str(context.workflow or ""),
        "ambiguity_reason": str(context.ambiguity_reason or ""),
        "clarify_reason": str(debug.get("clarify_reason") or ""),
        "attribute_filters": dict(context.attribute_filters or {}),
        "sku_tokens": list(context.sku_tokens or []),
        "suggested_questions": [str(item) for item in list(debug.get("clarify_questions") or [])[:3]],
        "suggested_examples": [str(item) for item in list(debug.get("clarify_suggestions") or [])[:3]],
    }


def _error_payload(context: ComponentContext) -> Dict[str, Any]:
    return {
        "user_text": str(context.user_text or ""),
        "query_summary": str(context.query_summary or ""),
        "workflow": str(context.workflow or ""),
        "source": str(getattr(context.source, "value", context.source) or ""),
        "result_count": int(context.result_count or 0),
        "has_attribute_filters": bool(context.attribute_filters),
        "has_sku_tokens": bool(context.sku_tokens),
        "internal_error_hint": str(context.error_message or ""),
    }


async def generate_contextual_component_message(
    *,
    kind: str,
    context: ComponentContext,
) -> str:
    if not bool(getattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", False)):
        return ""

    model = _copy_model()
    if not model:
        return ""

    if kind == "clarify":
        system_prompt = contextual_clarify_prompt(_reply_language(context))
        user_payload = _clarify_payload(context)
        usage_kind = "chat_component_clarify_copy"
    elif kind == "error":
        system_prompt = contextual_error_prompt(_reply_language(context))
        user_payload = _error_payload(context)
        usage_kind = "chat_component_error_copy"
    else:
        return ""

    try:
        data = await llm_service.generate_chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
            ],
            model=model,
            temperature=float(getattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_TEMPERATURE", 0.2)),
            max_tokens=int(getattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_MAX_TOKENS", 100)),
            usage_kind=usage_kind,
        )
    except Exception as exc:
        logger.warning("contextual component copy failed for %s: %s", kind, exc)
        return ""

    message = str((data or {}).get("message") or "").strip()
    if not message:
        return ""
    return " ".join(message.split())
