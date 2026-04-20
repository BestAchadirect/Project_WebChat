from __future__ import annotations

import json
import logging
from typing import Any, Dict, Mapping

from app.core.config import settings
from app.prompts.component_prompts import (
    contextual_clarify_prompt,
    contextual_default_reply_prompt,
    contextual_error_prompt,
    contextual_product_prompt,
    terminal_off_topic_prompt,
)
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


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _product_payload(context: ComponentContext, payload: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    data = dict(payload or {})
    products = list(getattr(context, "canonical_products", []) or [])
    top_products = []
    for product in products[:3]:
        attrs = dict(getattr(product, "attributes", {}) or {})
        top_products.append(
            {
                "sku": _normalize_text(getattr(product, "sku", "")),
                "title": _normalize_text(getattr(product, "title", "")),
                "material": _normalize_text(attrs.get("material") or getattr(product, "material", "")),
                "jewelry_type": _normalize_text(attrs.get("jewelry_type") or getattr(product, "jewelry_type", "")),
                "gauge": _normalize_text(attrs.get("gauge") or getattr(product, "gauge", "")),
                "master_code": _normalize_text(attrs.get("master_code")),
            }
        )
    data.setdefault("user_text", _normalize_text(context.user_text))
    data.setdefault("query_summary", _normalize_text(context.query_summary))
    data.setdefault("workflow", _normalize_text(context.workflow))
    data.setdefault("phrase", _normalize_text(data.get("phrase")))
    data.setdefault("focus_label", _normalize_text(data.get("focus_label")))
    data.setdefault("benefit_text", _normalize_text(data.get("benefit_text")))
    data.setdefault("attribute_filters", dict(getattr(context, "attribute_filters", {}) or {}))
    data.setdefault("result_count", int(getattr(context, "result_count", 0) or 0))
    data.setdefault("product_count", len(products))
    data.setdefault("products", top_products)
    return data


def _default_payload(context: ComponentContext, payload: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("user_text", _normalize_text(context.user_text))
    data.setdefault("query_summary", _normalize_text(context.query_summary))
    data.setdefault("workflow", _normalize_text(context.workflow))
    data.setdefault("source", _normalize_text(getattr(context.source, "value", context.source)))
    data.setdefault("result_count", int(getattr(context, "result_count", 0) or 0))
    data.setdefault("has_products", bool(list(getattr(context, "canonical_products", []) or [])))
    data.setdefault("has_knowledge", bool(list(getattr(context, "knowledge_sources", []) or [])))
    data.setdefault("attribute_filters", dict(getattr(context, "attribute_filters", {}) or {}))
    data.setdefault("sku_tokens", list(getattr(context, "sku_tokens", []) or []))
    data.setdefault("ambiguity_reason", _normalize_text(getattr(context, "ambiguity_reason", "")))
    return data


def _clarify_payload(context: ComponentContext) -> Dict[str, Any]:
    debug = dict(context.debug or {})
    return {
        "user_text": _normalize_text(context.user_text),
        "query_summary": _normalize_text(context.query_summary),
        "workflow": _normalize_text(context.workflow),
        "ambiguity_reason": _normalize_text(context.ambiguity_reason),
        "clarify_reason": _normalize_text(debug.get("clarify_reason")),
        "attribute_filters": dict(context.attribute_filters or {}),
        "sku_tokens": list(context.sku_tokens or []),
        "suggested_questions": [str(item) for item in list(debug.get("clarify_questions") or [])[:3]],
        "suggested_examples": [str(item) for item in list(debug.get("clarify_suggestions") or [])[:3]],
    }


def _error_payload(context: ComponentContext) -> Dict[str, Any]:
    return {
        "user_text": _normalize_text(context.user_text),
        "query_summary": _normalize_text(context.query_summary),
        "workflow": _normalize_text(context.workflow),
        "source": _normalize_text(getattr(context.source, "value", context.source)),
        "result_count": int(context.result_count or 0),
        "has_attribute_filters": bool(context.attribute_filters),
        "has_sku_tokens": bool(context.sku_tokens),
        "internal_error_hint": _normalize_text(context.error_message),
    }


async def _generate_json_reply(
    *,
    system_prompt: str,
    payload: Dict[str, Any],
    model: str,
    usage_kind: str,
    reply_key: str,
) -> str:
    try:
        data = await llm_service.generate_chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
            ],
            model=model,
            temperature=float(getattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_TEMPERATURE", 0.2)),
            max_tokens=int(getattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_MAX_TOKENS", 100)),
            usage_kind=usage_kind,
        )
    except Exception as exc:
        logger.warning("contextual component copy failed for %s: %s", usage_kind, exc)
        return ""

    message = str((data or {}).get(reply_key) or "").strip()
    if not message and reply_key != "message":
        message = str((data or {}).get("message") or "").strip()
    if not message and reply_key != "reply":
        message = str((data or {}).get("reply") or "").strip()
    return " ".join(message.split())


async def generate_contextual_reply(
    *,
    kind: str,
    reply_language: str,
    payload: Dict[str, Any],
) -> str:
    if not bool(getattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", False)):
        return ""

    model = _copy_model()
    if not model:
        return ""

    kind_norm = str(kind or "").strip().lower()
    if kind_norm == "clarify":
        system_prompt = contextual_clarify_prompt(reply_language)
        usage_kind = "chat_component_clarify_copy"
        reply_key = "message"
    elif kind_norm == "error":
        system_prompt = contextual_error_prompt(reply_language)
        usage_kind = "chat_component_error_copy"
        reply_key = "message"
    elif kind_norm == "product":
        system_prompt = contextual_product_prompt(reply_language)
        usage_kind = "chat_component_product_copy"
        reply_key = "reply"
    elif kind_norm == "default":
        system_prompt = contextual_default_reply_prompt(reply_language)
        usage_kind = "chat_component_default_copy"
        reply_key = "reply"
    elif kind_norm == "off_topic":
        system_prompt = terminal_off_topic_prompt(reply_language)
        usage_kind = "chat_component_off_topic_copy"
        reply_key = "reply"
    else:
        return ""

    return await _generate_json_reply(
        system_prompt=system_prompt,
        payload=dict(payload or {}),
        model=model,
        usage_kind=usage_kind,
        reply_key=reply_key,
    )


async def generate_contextual_component_message(
    *,
    kind: str,
    context: ComponentContext,
) -> str:
    reply_language = _reply_language(context)
    kind_norm = str(kind or "").strip().lower()
    if kind_norm == "clarify":
        return await generate_contextual_reply(
            kind="clarify",
            reply_language=reply_language,
            payload=_clarify_payload(context),
        )
    if kind_norm == "error":
        return await generate_contextual_reply(
            kind="error",
            reply_language=reply_language,
            payload=_error_payload(context),
        )
    if kind_norm == "product":
        return await generate_contextual_reply(
            kind="product",
            reply_language=reply_language,
            payload=_product_payload(context),
        )
    if kind_norm == "default":
        return await generate_contextual_reply(
            kind="default",
            reply_language=reply_language,
            payload=_default_payload(context),
        )
    return ""
