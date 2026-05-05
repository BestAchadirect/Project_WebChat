from __future__ import annotations

import json
from typing import Any, Dict, Sequence

from app.core.config import settings
from app.prompts.routing import understanding_workflow_prompt
from app.services.ai.llm_service import llm_service
from app.services.chat.routing import routing_policy
from app.services.chat.routing.contracts import (
    UnderstandingResult,
    normalize_assistant_intent,
    normalize_response_policy,
)

_ALLOWED_WORKFLOW_HYPOTHESES = {
    "catalog_search",
    "product_detail",
    "company_info",
    "policy_info",
    "mixed",
    "smalltalk",
    "general_talking",
    "off_topic",
    "clarify",
}

_LEGACY_WORKFLOW_BY_INTENT = {
    "product_information": "catalog_search",
    "knowledge_policy": "policy_info",
    "general_talking": "general_talking",
    "off_topic": "off_topic",
    "clarify": "clarify",
}


def _normalize_failure_reason(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _base_entity_hints(*, knowledge_tags: Sequence[str], has_sku: bool) -> Dict[str, Any]:
    return {
        "knowledge_tags": list(knowledge_tags or []),
        "has_sku": bool(has_sku),
        "has_company_signal": False,
        "has_policy_signal": False,
        "has_product_detail_signal": False,
        "has_product_search_signal": False,
        "has_smalltalk_signal": False,
        "has_off_topic_signal": False,
        "has_mixed_signal": False,
        "has_product_signal": False,
        "has_knowledge_signal": False,
        "preferred_knowledge_query": "",
        "preferred_store_overview_request": False,
    }


def _normalize_workflow_hypothesis(value: Any) -> str:
    workflow_hypothesis = str(value or "").strip().lower()
    if workflow_hypothesis in _ALLOWED_WORKFLOW_HYPOTHESES:
        return workflow_hypothesis
    return ""


def _default_response_policy_for_intent(*, intent: str, needs_products: bool, needs_knowledge: bool) -> str:
    intent_norm = normalize_assistant_intent(intent)
    if intent_norm in {"product_information", "knowledge_policy"} and (
        bool(needs_products) or bool(needs_knowledge)
    ):
        return "answer_from_retrieved_data"
    if intent_norm == "product_information":
        return "answer_from_allowed_capabilities"
    if intent_norm == "general_talking":
        return "friendly_scoped_reply"
    if intent_norm == "off_topic":
        return "safe_redirect"
    return "ask_clarifying_question"


def _coerce_response_policy_for_intent(
    *,
    intent: str,
    response_policy: str,
    needs_products: bool,
    needs_knowledge: bool,
) -> str:
    intent_norm = normalize_assistant_intent(intent)
    policy_norm = normalize_response_policy(response_policy)
    if intent_norm in {"product_information", "knowledge_policy"} and (
        bool(needs_products) or bool(needs_knowledge)
    ):
        return "answer_from_retrieved_data"
    if intent_norm == "product_information" and not bool(needs_products):
        return "answer_from_allowed_capabilities"
    if intent_norm == "general_talking" and policy_norm == "ask_clarifying_question":
        return "friendly_scoped_reply"
    if intent_norm == "off_topic":
        return "safe_redirect"
    return policy_norm


def _legacy_workflow_from_intent(*, intent: str, needs_products: bool, needs_knowledge: bool) -> str:
    intent_norm = normalize_assistant_intent(intent)
    if intent_norm == "product_information" and bool(needs_knowledge) and bool(needs_products):
        return "mixed"
    if intent_norm == "product_information" and not bool(needs_products):
        return "general_talking"
    return _LEGACY_WORKFLOW_BY_INTENT.get(intent_norm, "clarify")


def _coerce_hint_flag(data: Dict[str, Any], key: str) -> bool | None:
    if key not in data:
        return None
    value = data.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no", ""}:
        return False
    return None


def _entity_hints_from_llm_workflow(
    *,
    workflow_hypothesis: str,
    knowledge_query: str,
    store_overview_request: bool,
    needs_products: bool,
    needs_knowledge: bool,
    knowledge_tags: Sequence[str],
) -> Dict[str, Any]:
    workflow = str(workflow_hypothesis or "").strip().lower()
    has_company = workflow == "company_info"
    has_policy = workflow == "policy_info"
    has_product_detail = workflow == "product_detail"
    has_product_search = workflow in {"catalog_search", "mixed"}
    has_smalltalk = workflow == "smalltalk"
    has_off_topic = workflow == "off_topic"
    has_mixed = workflow == "mixed"
    return {
        "knowledge_tags": list(knowledge_tags or []),
        "has_company_signal": has_company,
        "has_policy_signal": has_policy,
        "has_product_detail_signal": has_product_detail,
        "has_product_search_signal": has_product_search,
        "has_smalltalk_signal": has_smalltalk,
        "has_off_topic_signal": has_off_topic,
        "has_mixed_signal": has_mixed,
        "has_product_signal": bool(needs_products or has_product_detail or has_product_search),
        "has_knowledge_signal": bool(needs_knowledge or has_company or has_policy or bool(knowledge_query)),
        "preferred_knowledge_query": str(knowledge_query or "").strip(),
        "preferred_store_overview_request": bool(store_overview_request),
    }


def _entity_hints_from_llm_payload(
    *,
    data: Dict[str, Any],
    workflow_hypothesis: str,
    knowledge_query: str,
    store_overview_request: bool,
    needs_products: bool,
    needs_knowledge: bool,
    knowledge_tags: Sequence[str],
    has_sku: bool,
    intent: str = "",
    product_query: str = "",
) -> Dict[str, Any]:
    intent_norm = normalize_assistant_intent(intent)
    if intent_norm != "clarify" or str(intent or "").strip().lower() == "clarify":
        effective_knowledge_tags = list(knowledge_tags or [])
        payload_knowledge_tags = data.get("knowledge_tags")
        if isinstance(payload_knowledge_tags, list):
            effective_knowledge_tags = [
                str(tag or "").strip().lower()
                for tag in payload_knowledge_tags
                if str(tag or "").strip()
            ]
        has_product = bool(intent_norm == "product_information" and (needs_products or product_query or has_sku))
        has_knowledge = bool(intent_norm == "knowledge_policy" and (needs_knowledge or knowledge_query))
        has_mixed = bool(intent_norm == "product_information" and needs_products and needs_knowledge)
        return {
            "knowledge_tags": effective_knowledge_tags,
            "has_sku": bool(has_sku),
            "has_company_signal": bool(intent_norm == "knowledge_policy" and store_overview_request),
            "has_policy_signal": bool(intent_norm == "knowledge_policy"),
            "has_product_detail_signal": bool(intent_norm == "product_information" and has_sku),
            "has_product_search_signal": bool(intent_norm == "product_information" and needs_products),
            "has_smalltalk_signal": bool(intent_norm == "general_talking"),
            "has_off_topic_signal": bool(intent_norm == "off_topic"),
            "has_mixed_signal": has_mixed,
            "has_product_signal": has_product,
            "has_knowledge_signal": has_knowledge,
            "preferred_knowledge_query": str(knowledge_query or "").strip(),
            "preferred_product_query": str(product_query or "").strip(),
            "preferred_store_overview_request": bool(store_overview_request),
        }

    fallback = _entity_hints_from_llm_workflow(
        workflow_hypothesis=workflow_hypothesis,
        knowledge_query=knowledge_query,
        store_overview_request=store_overview_request,
        needs_products=needs_products,
        needs_knowledge=needs_knowledge,
        knowledge_tags=knowledge_tags,
    )
    payload_knowledge_tags = data.get("knowledge_tags")
    if isinstance(payload_knowledge_tags, list):
        effective_knowledge_tags = [
            str(tag or "").strip().lower()
            for tag in payload_knowledge_tags
            if str(tag or "").strip()
        ]
    else:
        effective_knowledge_tags = list(knowledge_tags or [])
    entity_hints = _base_entity_hints(
        knowledge_tags=effective_knowledge_tags,
        has_sku=has_sku,
    )
    bool_keys = (
        "has_company_signal",
        "has_policy_signal",
        "has_product_detail_signal",
        "has_product_search_signal",
        "has_smalltalk_signal",
        "has_off_topic_signal",
        "has_mixed_signal",
        "has_product_signal",
        "has_knowledge_signal",
    )
    for key in bool_keys:
        explicit = _coerce_hint_flag(data, key)
        if explicit is None:
            entity_hints[key] = bool(fallback.get(key))
        else:
            entity_hints[key] = explicit

    preferred_knowledge_query = str(
        data.get("preferred_knowledge_query")
        or knowledge_query
        or fallback.get("preferred_knowledge_query")
        or ""
    ).strip()
    preferred_store_overview_request = _coerce_hint_flag(data, "preferred_store_overview_request")
    if preferred_store_overview_request is None:
        preferred_store_overview_request = bool(
            store_overview_request or fallback.get("preferred_store_overview_request")
        )

    entity_hints["preferred_knowledge_query"] = preferred_knowledge_query
    entity_hints["preferred_store_overview_request"] = bool(preferred_store_overview_request)
    entity_hints["has_product_signal"] = bool(
        entity_hints["has_product_signal"]
        or entity_hints["has_product_detail_signal"]
        or entity_hints["has_product_search_signal"]
        or needs_products
    )
    entity_hints["has_knowledge_signal"] = bool(
        entity_hints["has_knowledge_signal"]
        or entity_hints["has_company_signal"]
        or entity_hints["has_policy_signal"]
        or bool(preferred_knowledge_query)
        or needs_knowledge
    )
    entity_hints["has_sku"] = bool(has_sku)
    return entity_hints


def _workflow_hypothesis_from_entity_hints(entity_hints: Dict[str, Any]) -> str:
    if bool(entity_hints.get("has_smalltalk_signal")):
        return "smalltalk"
    if bool(entity_hints.get("has_off_topic_signal")):
        return "off_topic"
    if bool(entity_hints.get("has_mixed_signal")):
        return "mixed"
    if bool(entity_hints.get("has_policy_signal")):
        return "policy_info"
    if bool(entity_hints.get("has_company_signal")) or bool(
        entity_hints.get("preferred_store_overview_request")
    ):
        return "company_info"
    if bool(entity_hints.get("has_knowledge_signal")):
        return "policy_info"
    if bool(entity_hints.get("has_product_detail_signal")):
        return "product_detail"
    if bool(entity_hints.get("has_product_search_signal")) or bool(entity_hints.get("has_product_signal")):
        return "catalog_search"
    return "clarify"


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
    max_tokens = int(getattr(settings, "CHAT_INTENT_CLASSIFICATION_MAX_TOKENS", 500))
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
            reasoning_effort="minimal",
        )
        payload = dict(data or {})
        raw_workflow_hypothesis = _normalize_workflow_hypothesis(payload.get("workflow_hypothesis"))
        try:
            confidence = float(payload.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        intent = normalize_assistant_intent(payload.get("intent"))
        raw_intent = str(payload.get("intent") or "").strip().lower()
        product_query = str(payload.get("product_query") or "").strip()
        knowledge_query = str(payload.get("knowledge_query") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        store_overview_request = bool(payload.get("store_overview_request"))
        needs_products = bool(payload.get("needs_products"))
        needs_knowledge = bool(payload.get("needs_knowledge"))
        response_policy = _coerce_response_policy_for_intent(
            intent=intent,
            response_policy=(
                payload.get("response_policy")
                or _default_response_policy_for_intent(
                    intent=intent,
                    needs_products=needs_products,
                    needs_knowledge=needs_knowledge,
                )
            ),
            needs_products=needs_products,
            needs_knowledge=needs_knowledge,
        )
        subintent = str(payload.get("subintent") or "").strip()
        user_goal = str(payload.get("user_goal") or "").strip()
        clarify_question = str(payload.get("clarify_question") or "").strip()
        pending_task_type = str(payload.get("pending_task_type") or "").strip().lower()
        missing_slot = str(payload.get("missing_slot") or "").strip().lower()
        if intent == "clarify" and not pending_task_type and "origin" in subintent.lower():
            pending_task_type = "product_origin_question"
            missing_slot = missing_slot or "product_anchor"
        if raw_intent:
            raw_workflow_hypothesis = _legacy_workflow_from_intent(
                intent=intent,
                needs_products=needs_products,
                needs_knowledge=needs_knowledge,
            )
        debug["understanding_used_llm"] = True
        debug["understanding_llm_confidence"] = confidence
        debug["understanding_llm_workflow"] = raw_workflow_hypothesis or "clarify"
        if raw_intent:
            debug["understanding_intent"] = intent
            debug["understanding_response_policy"] = response_policy
            debug["understanding_pending_task_type"] = pending_task_type
            debug["understanding_missing_slot"] = missing_slot
        debug["understanding_reason"] = reason
        entity_hints = _entity_hints_from_llm_payload(
            data=payload,
            workflow_hypothesis=raw_workflow_hypothesis or "clarify",
            knowledge_query=knowledge_query,
            store_overview_request=store_overview_request,
            needs_products=needs_products,
            needs_knowledge=needs_knowledge,
            knowledge_tags=knowledge_tags,
            has_sku=bool(sku_tokens),
            intent=intent if raw_intent else "",
            product_query=product_query,
        )
        workflow_hypothesis = _workflow_hypothesis_from_entity_hints(entity_hints)
        if raw_intent:
            workflow_hypothesis = _legacy_workflow_from_intent(
                intent=intent,
                needs_products=bool(entity_hints.get("has_product_signal") or needs_products),
                needs_knowledge=bool(entity_hints.get("has_knowledge_signal") or needs_knowledge),
            )
        debug["understanding_llm_workflow_effective"] = workflow_hypothesis
        return UnderstandingResult(
            normalized_text=clean_text,
            locale=locale,
            channel=channel,
            sku_tokens=list(sku_tokens or []),
            workflow_hypothesis=workflow_hypothesis,
            intent_confidence=confidence,
            reason=reason,
            knowledge_query=str(entity_hints.get("preferred_knowledge_query") or knowledge_query),
            store_overview_request=bool(
                entity_hints.get("preferred_store_overview_request") or store_overview_request
            ),
            needs_products=bool(entity_hints.get("has_product_signal") or needs_products),
            needs_knowledge=bool(entity_hints.get("has_knowledge_signal") or needs_knowledge),
            intent=intent if raw_intent else "",
            subintent=subintent,
            user_goal=user_goal,
            product_query=str(entity_hints.get("preferred_product_query") or product_query),
            response_policy=response_policy,
            clarify_question=clarify_question,
            pending_task_type=pending_task_type,
            missing_slot=missing_slot,
            failure_reason="",
            entity_hints=entity_hints,
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
            intent="clarify",
            response_policy="ask_clarifying_question",
            failure_reason=f"understanding_failed:{failure_reason}",
            entity_hints=_base_entity_hints(
                knowledge_tags=knowledge_tags,
                has_sku=bool(sku_tokens),
            ),
            debug=debug,
        )


async def build_understanding_result(
    *,
    user_text: str,
    locale: str | None,
    channel: str | None,
    sku_tokens: Sequence[str] | None = None,
) -> UnderstandingResult:
    clean_text = str(user_text or "").strip()
    locale_value = str(locale or "")
    channel_value = str(channel or "")
    sku_list = list(sku_tokens or routing_policy.extract_sku_tokens(clean_text))
    knowledge_tags: list[str] = []
    entity_hints: Dict[str, Any] = _base_entity_hints(
        knowledge_tags=knowledge_tags,
        has_sku=bool(sku_list),
    )
    debug: Dict[str, Any] = {
        "understanding_source": "empty",
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
            intent="clarify",
            response_policy="ask_clarifying_question",
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
