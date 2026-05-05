from __future__ import annotations

from typing import Optional

from app.services.chat.components.types import ComponentSource
from app.services.chat.routing import routing_policy
from app.services.chat.routing.signals import classify_fallback_reason
from app.services.chat.routing.contracts import DecisionState, UnderstandingResult
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities, build_chat_runtime_capabilities


def _source_for_public_workflow(public_workflow: str) -> ComponentSource:
    if public_workflow == "catalog":
        return ComponentSource.SQL
    if public_workflow == "knowledge":
        return ComponentSource.KNOWLEDGE
    return ComponentSource.ERROR


def _entity_hint_bool(understanding: UnderstandingResult, key: str) -> bool:
    return bool((understanding.entity_hints or {}).get(key))


def _entity_hint_text(understanding: UnderstandingResult, key: str) -> str:
    return str((understanding.entity_hints or {}).get(key) or "").strip()


_COMPANY_INFO_SUBINTENTS = {
    "about_company",
    "assistant_handoff",
    "company_contact",
    "company_info",
    "company_profile",
    "contact",
    "human_help",
    "location",
    "sales_contact",
    "showroom",
    "store_hours",
    "store_location",
    "store_overview",
    "support",
    "support_contact",
}


def _uses_response_intent_contract(understanding: UnderstandingResult) -> bool:
    debug = dict(getattr(understanding, "debug", {}) or {})
    intent = str(getattr(understanding, "intent", "") or "").strip().lower()
    response_policy = str(getattr(understanding, "response_policy", "") or "").strip().lower()
    return bool(
        debug.get("understanding_intent")
        or intent in {"product_information", "knowledge_policy", "general_talking", "off_topic"}
        or response_policy
        not in {
            "",
            "ask_clarifying_question",
        }
        or str(getattr(understanding, "subintent", "") or "").strip()
        or str(getattr(understanding, "user_goal", "") or "").strip()
        or str(getattr(understanding, "product_query", "") or "").strip()
        or str(getattr(understanding, "clarify_question", "") or "").strip()
        or str(getattr(understanding, "pending_task_type", "") or "").strip()
        or str(getattr(understanding, "missing_slot", "") or "").strip()
    )


def _is_company_info_request(understanding: UnderstandingResult) -> bool:
    if not _uses_response_intent_contract(understanding):
        return bool(
            _entity_hint_bool(understanding, "has_company_signal")
            or understanding.workflow_hypothesis == "company_info"
        )

    intent = str(getattr(understanding, "intent", "") or "").strip().lower()
    if intent != "knowledge_policy":
        return False

    subintent = str(getattr(understanding, "subintent", "") or "").strip().lower()
    if subintent:
        subintent_parts = {
            part
            for part in subintent.replace("/", " ").replace("-", " ").replace("_", " ").split()
            if part
        }
        return bool(
            subintent in _COMPANY_INFO_SUBINTENTS
            or subintent_parts.intersection(_COMPANY_INFO_SUBINTENTS)
        )

    return bool(understanding.store_overview_request)


def _derive_internal_workflow(understanding: UnderstandingResult) -> str:
    if not str(understanding.normalized_text or "").strip():
        return "clarify"
    if _uses_response_intent_contract(understanding):
        intent = str(getattr(understanding, "intent", "") or "").strip().lower()
        if intent == "product_information":
            if bool(understanding.needs_products) and bool(understanding.needs_knowledge):
                return "mixed"
            if bool(understanding.needs_products):
                return "product_detail" if list(understanding.sku_tokens or []) else "catalog_search"
            return "general_talking"
        if intent == "knowledge_policy":
            if _is_company_info_request(understanding):
                return "company_info"
            return "policy_info"
        if intent == "general_talking":
            return "general_talking"
        if intent == "off_topic":
            return "off_topic"
        return "clarify"
    if _entity_hint_bool(understanding, "has_smalltalk_signal"):
        return "smalltalk"
    if _entity_hint_bool(understanding, "has_off_topic_signal"):
        return "off_topic"
    if _entity_hint_bool(understanding, "has_mixed_signal"):
        return "mixed"
    if _entity_hint_bool(understanding, "has_company_signal"):
        return "company_info"
    if _entity_hint_bool(understanding, "has_policy_signal"):
        return "policy_info"
    if _entity_hint_bool(understanding, "has_product_detail_signal"):
        return "product_detail"
    if _entity_hint_bool(understanding, "has_product_search_signal") or _entity_hint_bool(
        understanding,
        "has_product_signal",
    ):
        return "catalog_search"
    return "clarify"


def _derive_public_workflow(understanding: UnderstandingResult) -> str:
    if not str(understanding.normalized_text or "").strip():
        return "fallback"
    if _uses_response_intent_contract(understanding):
        intent = str(getattr(understanding, "intent", "") or "").strip().lower()
        if intent == "product_information":
            return "catalog" if bool(understanding.needs_products) else "general_talking"
        if intent == "knowledge_policy":
            return "knowledge" if bool(understanding.needs_knowledge) else "general_talking"
        if intent == "general_talking":
            return "general_talking"
        if intent == "off_topic":
            return "off_topic"
        return "fallback"
    if str(understanding.failure_reason or "").strip() and not (
        _entity_hint_bool(understanding, "has_product_signal")
        or _entity_hint_bool(understanding, "has_knowledge_signal")
        or _entity_hint_bool(understanding, "has_smalltalk_signal")
        or _entity_hint_bool(understanding, "has_off_topic_signal")
    ):
        return "fallback"
    if _entity_hint_bool(understanding, "has_smalltalk_signal") or _entity_hint_bool(
        understanding,
        "has_off_topic_signal",
    ):
        return "off_topic"
    if _entity_hint_bool(understanding, "has_product_signal"):
        return "catalog"
    if _entity_hint_bool(understanding, "has_knowledge_signal"):
        return "knowledge"
    return "fallback"


def _fallback_reason(understanding: UnderstandingResult) -> str:
    if str(understanding.failure_reason or "").strip():
        return "routing_fallback"
    if (
        str(getattr(understanding, "pending_task_type", "") or "").strip()
        and str(getattr(understanding, "missing_slot", "") or "").strip()
    ):
        return "pending_task_missing_slot"
    return classify_fallback_reason(
        text=str(understanding.normalized_text or ""),
        route_reason=str(understanding.reason or ""),
        blank_reason="fallback_missing_signal",
        default_reason="fallback_vague_store_request",
        has_product_signal=any(
            _entity_hint_bool(understanding, key)
            for key in (
                "has_product_signal",
                "has_knowledge_signal",
                "has_product_search_signal",
                "has_product_detail_signal",
                "has_policy_signal",
                "has_company_signal",
            )
        ),
        has_knowledge_signal=_entity_hint_bool(understanding, "has_knowledge_signal"),
        has_smalltalk_signal=_entity_hint_bool(understanding, "has_smalltalk_signal"),
        has_off_topic_signal=_entity_hint_bool(understanding, "has_off_topic_signal"),
    )


def _build_route_decision(understanding: UnderstandingResult) -> routing_policy.WorkflowDecision:
    public_workflow = _derive_public_workflow(understanding)
    if public_workflow == "fallback":
        reason = _fallback_reason(understanding)
        return routing_policy.WorkflowDecision(
            workflow="fallback",
            source=ComponentSource.ERROR,
            needs_products=False,
            needs_knowledge=False,
            needs_clarification=True,
            store_overview_request=False,
            knowledge_query="",
            reason=reason,
            confidence=float(understanding.intent_confidence or 0.0),
        )

    has_product_signal = _entity_hint_bool(understanding, "has_product_signal")
    has_knowledge_signal = _entity_hint_bool(understanding, "has_knowledge_signal")
    preferred_knowledge_query = _entity_hint_text(understanding, "preferred_knowledge_query")
    preferred_store_overview_request = _entity_hint_bool(
        understanding,
        "preferred_store_overview_request",
    )
    store_overview_request = bool(
        preferred_store_overview_request or understanding.store_overview_request
    )
    if _uses_response_intent_contract(understanding):
        store_overview_request = bool(
            store_overview_request and _is_company_info_request(understanding)
        )

    needs_products = bool(has_product_signal or understanding.needs_products or public_workflow == "catalog")
    needs_knowledge = bool(
        has_knowledge_signal
        or understanding.needs_knowledge
        or public_workflow == "knowledge"
    )
    needs_clarification = False
    if public_workflow == "off_topic":
        needs_products = False
        needs_knowledge = False
        needs_clarification = False

    return routing_policy.WorkflowDecision(
        workflow=public_workflow,
        source=_source_for_public_workflow(public_workflow),
        needs_products=needs_products,
        needs_knowledge=needs_knowledge,
        needs_clarification=needs_clarification,
        store_overview_request=store_overview_request,
        knowledge_query=(
            (preferred_knowledge_query or str(understanding.knowledge_query or "").strip())
            if needs_knowledge
            else ""
        ),
        reason=str(understanding.reason or public_workflow),
        confidence=float(understanding.intent_confidence or 0.0),
    )


def _supports_agentic_route(route_decision: routing_policy.WorkflowDecision) -> bool:
    workflow = str(route_decision.workflow or "").strip().lower()
    if workflow not in routing_policy.AGENTIC_SUPPORTED_WORKFLOWS:
        return False
    if bool(route_decision.needs_clarification):
        return False
    return bool(route_decision.needs_products or route_decision.needs_knowledge)


def build_decision_state(
    *,
    understanding: UnderstandingResult,
    user_text: str,
    channel: Optional[str],
    capabilities: ChatRuntimeCapabilities | None = None,
) -> DecisionState:
    caps = capabilities or build_chat_runtime_capabilities()
    internal_workflow = _derive_internal_workflow(understanding)
    route_decision = _build_route_decision(understanding)
    public_workflow = route_decision.workflow

    execution_mode = "component"
    selection_source = str(understanding.debug.get("understanding_source") or "understanding")
    feature_enabled = bool(caps.agentic_function_calling_enabled)
    channel_allowed = routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps)
    sku_token = str((understanding.sku_tokens or [None])[0] or "")
    tool_suitable = routing_policy.is_agentic_tool_suitable(
        user_text=user_text,
        workflow=route_decision.workflow,
        sku_token=sku_token or None,
        needs_products=route_decision.needs_products,
        needs_knowledge=route_decision.needs_knowledge,
    )
    route_supports_agentic = _supports_agentic_route(route_decision)

    if feature_enabled and channel_allowed and route_supports_agentic and tool_suitable:
        execution_mode = "agentic"
        selection_source = "agentic"

    execution_decision = routing_policy.ExecutionDecision(
        route_decision=route_decision,
        execution_mode=execution_mode,
        reason=str(understanding.reason or internal_workflow or public_workflow),
        feature_enabled=feature_enabled,
        channel_allowed=channel_allowed,
        tool_suitable=tool_suitable,
        selection_source=selection_source,
        llm_reason=str(understanding.reason or ""),
        llm_confidence=float(understanding.intent_confidence or 0.0),
        llm_workflow=public_workflow,
        llm_execution_mode=execution_mode,
    )

    return DecisionState(
        internal_workflow=internal_workflow,
        public_workflow=public_workflow,
        intent_confidence=float(understanding.intent_confidence or 0.0),
        retrieval_confidence=0.0,
        answerability="none",
        reason=str(understanding.reason or ""),
        failure_reason=str(understanding.failure_reason or ""),
        knowledge_query=str(route_decision.knowledge_query or ""),
        store_overview_request=bool(route_decision.store_overview_request),
        needs_products=bool(route_decision.needs_products),
        needs_knowledge=bool(route_decision.needs_knowledge),
        intent=str(getattr(understanding, "intent", "") or ""),
        subintent=str(getattr(understanding, "subintent", "") or ""),
        user_goal=str(getattr(understanding, "user_goal", "") or ""),
        product_query=str(getattr(understanding, "product_query", "") or ""),
        response_policy=str(getattr(understanding, "response_policy", "") or ""),
        clarify_question=str(getattr(understanding, "clarify_question", "") or ""),
        pending_task_type=str(getattr(understanding, "pending_task_type", "") or ""),
        missing_slot=str(getattr(understanding, "missing_slot", "") or ""),
        entity_hints=dict(understanding.entity_hints or {}),
        route_decision=route_decision,
        execution_decision=execution_decision,
        debug={
            "understanding_source": str(understanding.debug.get("understanding_source") or ""),
            "understanding_reason": str(understanding.reason or ""),
            "understanding_failure_reason": str(understanding.failure_reason or ""),
            "understanding_intent": str(getattr(understanding, "intent", "") or ""),
            "understanding_subintent": str(getattr(understanding, "subintent", "") or ""),
            "understanding_user_goal": str(getattr(understanding, "user_goal", "") or ""),
            "understanding_product_query": str(getattr(understanding, "product_query", "") or ""),
            "understanding_response_policy": str(getattr(understanding, "response_policy", "") or ""),
            "understanding_clarify_question": str(getattr(understanding, "clarify_question", "") or ""),
            "understanding_pending_task_type": str(getattr(understanding, "pending_task_type", "") or ""),
            "understanding_missing_slot": str(getattr(understanding, "missing_slot", "") or ""),
            "internal_workflow": internal_workflow,
        },
    )
