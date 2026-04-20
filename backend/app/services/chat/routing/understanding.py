from __future__ import annotations

import json
from typing import Any, Dict, Sequence

from app.core.config import settings
from app.prompts.routing import understanding_workflow_prompt
from app.services.ai.llm_service import llm_service
from app.services.chat.routing import routing_policy
from app.services.chat.routing.contracts import UnderstandingResult
from app.services.chat.routing.signals import (
    build_company_query,
    has_company_signal,
    has_policy_signal,
    is_smalltalk,
    looks_like_product_detail,
    looks_like_product_search,
    normalize_signal_text,
)
from app.services.knowledge.tagging import build_knowledge_query_tags


def _normalize_text(text: Any) -> str:
    return normalize_signal_text(str(text or ""))


def _normalize_failure_reason(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


async def _llm_understanding(
    *,
    clean_text: str,
    locale: str,
    channel: str,
    sku_tokens: Sequence[str],
    knowledge_tags: Sequence[str],
) -> UnderstandingResult:
    debug: Dict[str, Any] = {
        "understanding_source": "llm",
        "understanding_used_llm": False,
        "understanding_llm_confidence": 0.0,
        "understanding_llm_workflow": "",
        "understanding_reason": "",
    }
    model = str(
        getattr(settings, "CHAT_INTENT_CLASSIFICATION_MODEL", "")
        or getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MODEL", "")
        or getattr(settings, "NLU_MODEL", "gpt-5-mini")
    ).strip()
    max_tokens = int(getattr(settings, "CHAT_INTENT_CLASSIFICATION_MAX_TOKENS", 160))
    system_prompt = understanding_workflow_prompt()
    user_payload = {
        "query": clean_text,
        "locale": locale,
        "channel": channel,
        "sku_tokens": list(sku_tokens or []),
        "knowledge_tags": list(knowledge_tags or []),
    }
    try:
        data = await llm_service.generate_chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
            ],
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
            usage_kind="chat_understanding",
        )
        workflow_hypothesis = str((data or {}).get("workflow_hypothesis") or "").strip().lower()
        if workflow_hypothesis not in {
            "catalog_search",
            "product_detail",
            "company_info",
            "policy_info",
            "mixed",
            "smalltalk",
            "off_topic",
            "clarify",
        }:
            workflow_hypothesis = "clarify"
        try:
            confidence = float((data or {}).get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        knowledge_query = str((data or {}).get("knowledge_query") or "").strip()
        reason = str((data or {}).get("reason") or "").strip()
        store_overview_request = bool((data or {}).get("store_overview_request"))
        needs_products = bool((data or {}).get("needs_products"))
        needs_knowledge = bool((data or {}).get("needs_knowledge"))
        debug["understanding_used_llm"] = True
        debug["understanding_llm_confidence"] = confidence
        debug["understanding_llm_workflow"] = workflow_hypothesis
        debug["understanding_reason"] = reason
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale,
            channel=channel,
            sku_tokens=list(sku_tokens or []),
            workflow_hypothesis=workflow_hypothesis,
            intent_confidence=confidence,
            reason=reason,
            knowledge_query=knowledge_query,
            store_overview_request=store_overview_request,
            needs_products=needs_products,
            needs_knowledge=needs_knowledge,
            failure_reason="",
            entity_hints={"knowledge_tags": list(knowledge_tags or [])},
            llm_call_count=1,
            debug=debug,
        )
    except Exception as exc:
        failure_reason = _normalize_failure_reason(type(exc).__name__ or "understanding_error")
        debug["understanding_error"] = str(exc)
        debug["understanding_failure_reason"] = f"understanding_failed:{failure_reason}"
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale,
            channel=channel,
            sku_tokens=list(sku_tokens or []),
            workflow_hypothesis="clarify",
            intent_confidence=0.0,
            reason="routing_fallback",
            failure_reason=f"understanding_failed:{failure_reason}",
            entity_hints={"knowledge_tags": list(knowledge_tags or [])},
            debug=debug,
        )


async def build_understanding_result(
    *,
    user_text: str,
    locale: str | None,
    channel: str | None,
    sku_tokens: Sequence[str] | None = None,
) -> UnderstandingResult:
    clean_text = _normalize_text(user_text)
    locale_value = str(locale or "")
    channel_value = str(channel or "")
    sku_list = list(sku_tokens or routing_policy.extract_sku_tokens(clean_text))
    knowledge_tags = build_knowledge_query_tags(clean_text)
    entity_hints: Dict[str, Any] = {
        "knowledge_tags": list(knowledge_tags or []),
        "has_sku": bool(sku_list),
    }
    debug: Dict[str, Any] = {
        "understanding_source": "deterministic",
        "understanding_used_llm": False,
        "understanding_reason": "",
    }

    if not clean_text:
        debug["understanding_reason"] = "empty_message"
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale_value,
            channel=channel_value,
            sku_tokens=sku_list,
            workflow_hypothesis="clarify",
            intent_confidence=0.0,
            reason="empty_message",
            failure_reason="",
            entity_hints=entity_hints,
            debug=debug,
        )

    has_company = has_company_signal(clean_text, knowledge_tags)
    has_policy = has_policy_signal(clean_text, knowledge_tags)
    has_product_detail = looks_like_product_detail(clean_text, sku_list)
    has_product_search = looks_like_product_search(clean_text)
    entity_hints.update(
        {
            "has_company_signal": has_company,
            "has_policy_signal": has_policy,
            "has_product_detail_signal": has_product_detail,
            "has_product_search_signal": has_product_search,
        }
    )

    if is_smalltalk(clean_text) and not (has_company or has_policy or has_product_search or has_product_detail):
        debug["understanding_reason"] = "smalltalk_detected"
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale_value,
            channel=channel_value,
            sku_tokens=sku_list,
            workflow_hypothesis="smalltalk",
            intent_confidence=0.96,
            reason="smalltalk_detected",
            failure_reason="",
            entity_hints=entity_hints,
            debug=debug,
        )

    if (has_company or has_policy) and (has_product_search or has_product_detail):
        knowledge_query, store_overview_request = build_company_query(clean_text, knowledge_tags)
        if has_policy and not has_company:
            knowledge_query = clean_text
            store_overview_request = False
        debug["understanding_reason"] = "mixed_signals_detected"
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale_value,
            channel=channel_value,
            sku_tokens=sku_list,
            workflow_hypothesis="mixed",
            intent_confidence=0.92,
            reason="mixed_signals_detected",
            knowledge_query=knowledge_query,
            store_overview_request=store_overview_request,
            needs_products=True,
            needs_knowledge=True,
            failure_reason="",
            entity_hints=entity_hints,
            debug=debug,
        )

    if has_company:
        knowledge_query, store_overview_request = build_company_query(clean_text, knowledge_tags)
        debug["understanding_reason"] = "company_signal_detected"
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale_value,
            channel=channel_value,
            sku_tokens=sku_list,
            workflow_hypothesis="company_info",
            intent_confidence=0.95,
            reason="company_signal_detected",
            knowledge_query=knowledge_query,
            store_overview_request=store_overview_request,
            needs_products=False,
            needs_knowledge=True,
            failure_reason="",
            entity_hints=entity_hints,
            debug=debug,
        )

    if has_policy:
        debug["understanding_reason"] = "policy_signal_detected"
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale_value,
            channel=channel_value,
            sku_tokens=sku_list,
            workflow_hypothesis="policy_info",
            intent_confidence=0.9,
            reason="policy_signal_detected",
            knowledge_query=clean_text,
            needs_products=False,
            needs_knowledge=True,
            failure_reason="",
            entity_hints=entity_hints,
            debug=debug,
        )

    if has_product_detail:
        debug["understanding_reason"] = "product_detail_signal_detected"
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale_value,
            channel=channel_value,
            sku_tokens=sku_list,
            workflow_hypothesis="product_detail",
            intent_confidence=0.93,
            reason="product_detail_signal_detected",
            needs_products=True,
            needs_knowledge=False,
            failure_reason="",
            entity_hints=entity_hints,
            debug=debug,
        )

    if has_product_search:
        debug["understanding_reason"] = "catalog_signal_detected"
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale_value,
            channel=channel_value,
            sku_tokens=sku_list,
            workflow_hypothesis="catalog_search",
            intent_confidence=0.86,
            reason="catalog_signal_detected",
            needs_products=True,
            needs_knowledge=False,
            failure_reason="",
            entity_hints=entity_hints,
            debug=debug,
        )

    return await _llm_understanding(
        clean_text=clean_text,
        locale=locale_value,
        channel=channel_value,
        sku_tokens=sku_list,
        knowledge_tags=knowledge_tags,
    )
