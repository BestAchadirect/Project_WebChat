from __future__ import annotations

from typing import Optional

from app.services.chat.components.types import ComponentSource
from app.services.chat.routing import routing_policy
from app.services.chat.routing import signals as routing_signals
from app.services.chat.routing.signals import classify_fallback_reason
from app.services.chat.routing.contracts import DecisionState, UnderstandingResult
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities, build_chat_runtime_capabilities


def _source_for_public_workflow(public_workflow: str) -> ComponentSource:
    if public_workflow == "catalog":
        return ComponentSource.SQL
    if public_workflow == "knowledge":
        return ComponentSource.KNOWLEDGE
    return ComponentSource.ERROR


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

_CONTACT_LIKE_SUBINTENTS = {
    "contact",
    "company_contact",
    "sales_contact",
    "support",
    "support_contact",
    "human_help",
    "assistant_handoff",
    "store_overview",
    "store_location",
    "location",
    "showroom",
    "store_hours",
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


def _is_contact_like_request(understanding: UnderstandingResult) -> bool:
    intent = str(getattr(understanding, "intent", "") or "").strip().lower()
    if intent not in {"knowledge_policy", "general_talking"}:
        return False

    subintent = str(getattr(understanding, "subintent", "") or "").strip().lower()
    if not subintent:
        return False

    subintent_parts = {
        part
        for part in subintent.replace("/", " ").replace("-", " ").replace("_", " ").split()
        if part
    }
    return bool(subintent in _CONTACT_LIKE_SUBINTENTS or subintent_parts.intersection(_CONTACT_LIKE_SUBINTENTS))


def _is_company_info_request(understanding: UnderstandingResult) -> bool:
    legacy_workflow = str(getattr(understanding, "workflow_hypothesis", "") or "").strip().lower()
    if legacy_workflow == "company_info":
        return True

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
            or subintent in _CONTACT_LIKE_SUBINTENTS
            or subintent_parts.intersection(_CONTACT_LIKE_SUBINTENTS)
        )

    return bool(understanding.store_overview_request)


def _is_unscoped_general_task(understanding: UnderstandingResult) -> bool:
    intent = str(getattr(understanding, "intent", "") or "").strip().lower()
    if intent != "general_talking":
        return False
    response_policy = str(getattr(understanding, "response_policy", "") or "").strip().lower()
    if response_policy != "answer_from_allowed_capabilities":
        return False
    return bool(
        str(getattr(understanding, "pending_task_type", "") or "").strip()
        and str(getattr(understanding, "missing_slot", "") or "").strip()
    )


def _derive_internal_workflow(understanding: UnderstandingResult) -> str:
    if not str(understanding.normalized_text or "").strip():
        return "clarify"
    legacy_workflow = str(getattr(understanding, "workflow_hypothesis", "") or "").strip().lower()
    compare_request = routing_signals.looks_like_compare_request(
        text=str(understanding.normalized_text or ""),
        sku_tokens=understanding.sku_tokens or [],
    )
    if _uses_response_intent_contract(understanding):
        intent = str(getattr(understanding, "intent", "") or "").strip().lower()
        legacy_workflow = str(getattr(understanding, "workflow_hypothesis", "") or "").strip().lower()
        response_policy = str(getattr(understanding, "response_policy", "") or "").strip().lower()
        if intent == "product_information":
            if compare_request and len(list(understanding.sku_tokens or [])) >= 2:
                return "compare_products"
            if bool(understanding.needs_products) and bool(understanding.needs_knowledge):
                return "mixed"
            if bool(understanding.needs_products):
                return "product_detail" if list(understanding.sku_tokens or []) else "catalog_search"
            if bool(understanding.needs_knowledge):
                return "policy_info"
            return "general_talking"
        if intent == "knowledge_policy":
            if bool(understanding.needs_products) and bool(understanding.needs_knowledge):
                return "mixed"
            if _is_company_info_request(understanding):
                return "company_info"
            return "policy_info"
        if intent == "general_talking":
            if _is_unscoped_general_task(understanding):
                return "off_topic"
            if _is_contact_like_request(understanding):
                return "company_info"
            if bool(understanding.needs_knowledge) or response_policy == "answer_from_retrieved_data":
                return "policy_info"
            return "general_talking"
        if intent == "off_topic":
            return "off_topic"
        if intent == "clarify":
            if compare_request and len(list(understanding.sku_tokens or [])) >= 2:
                return "compare_products"
            if bool(understanding.needs_products) and bool(understanding.needs_knowledge):
                return "mixed"
            if bool(understanding.needs_products):
                return "product_detail" if list(understanding.sku_tokens or []) else "catalog_search"
            if bool(understanding.needs_knowledge):
                return "company_info" if _is_company_info_request(understanding) else "policy_info"
            response_policy = str(getattr(understanding, "response_policy", "") or "").strip().lower()
            if response_policy == "safe_redirect":
                return "off_topic"
            return "clarify"
        if legacy_workflow in {"company_info", "policy_info", "mixed", "smalltalk", "off_topic", "catalog_search", "product_detail"}:
            return legacy_workflow
        return "clarify"
    if legacy_workflow in {"company_info", "policy_info", "mixed", "smalltalk", "general_talking", "off_topic", "catalog_search", "product_detail"}:
        return legacy_workflow
    return "clarify"


def _derive_public_workflow(understanding: UnderstandingResult) -> str:
    if not str(understanding.normalized_text or "").strip():
        return "fallback"
    legacy_workflow = str(getattr(understanding, "workflow_hypothesis", "") or "").strip().lower()
    if _uses_response_intent_contract(understanding):
        intent = str(getattr(understanding, "intent", "") or "").strip().lower()
        response_policy = str(getattr(understanding, "response_policy", "") or "").strip().lower()
        if intent == "product_information":
            if bool(understanding.needs_products):
                return "catalog"
            if bool(understanding.needs_knowledge):
                return "knowledge"
            return "general_talking"
        if intent == "knowledge_policy":
            if bool(understanding.needs_products) and bool(understanding.needs_knowledge):
                return "catalog"
            return "knowledge" if bool(understanding.needs_knowledge) else "general_talking"
        if intent == "general_talking":
            if _is_unscoped_general_task(understanding):
                return "off_topic"
            if _is_contact_like_request(understanding):
                return "knowledge"
            if bool(understanding.needs_knowledge) or response_policy == "answer_from_retrieved_data":
                return "knowledge"
            return "general_talking"
        if intent == "off_topic":
            return "off_topic"
        if intent == "clarify":
            if bool(understanding.needs_products):
                return "catalog"
            if bool(understanding.needs_knowledge):
                return "knowledge"
            response_policy = str(getattr(understanding, "response_policy", "") or "").strip().lower()
            if response_policy == "safe_redirect":
                return "off_topic"
            return "fallback"
        if legacy_workflow in {"company_info", "policy_info"}:
            return "knowledge"
        if legacy_workflow in {"mixed", "catalog_search", "product_detail"}:
            return "catalog"
        if legacy_workflow == "smalltalk":
            return "general_talking"
        if legacy_workflow == "off_topic":
            return "off_topic"
        return "fallback"
    if legacy_workflow in {"company_info", "policy_info"}:
        return "knowledge"
    if legacy_workflow in {"mixed", "catalog_search", "product_detail"}:
        return "catalog"
    if legacy_workflow in {"smalltalk", "general_talking"}:
        return "general_talking"
    if legacy_workflow == "off_topic":
        return "off_topic"
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
        has_product_signal=bool(understanding.needs_products),
        has_knowledge_signal=bool(understanding.needs_knowledge),
        has_smalltalk_signal=str(getattr(understanding, "intent", "") or "").strip().lower() == "general_talking",
        has_off_topic_signal=str(getattr(understanding, "intent", "") or "").strip().lower() == "off_topic",
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

    needs_products = bool(understanding.needs_products or public_workflow == "catalog")
    needs_knowledge = bool(understanding.needs_knowledge or public_workflow == "knowledge")
    needs_clarification = bool(public_workflow == "fallback")
    store_overview_request = bool(
        understanding.store_overview_request and _is_company_info_request(understanding)
    )
    if public_workflow == "off_topic":
        needs_products = False
        needs_knowledge = False
        needs_clarification = False

    preferred_knowledge_query = str(getattr(understanding, "knowledge_query", "") or "").strip()

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


def _agentic_selection_blockers(
    *,
    route_decision: routing_policy.WorkflowDecision,
    feature_enabled: bool,
    channel_allowed: bool,
    route_supported: bool,
    tool_suitable: bool,
) -> tuple[str, ...]:
    blockers: list[str] = []
    workflow = str(route_decision.workflow or "").strip().lower()
    if not feature_enabled:
        blockers.append("feature_disabled")
    elif not channel_allowed:
        blockers.append("channel_not_allowed")
    if workflow not in routing_policy.AGENTIC_SUPPORTED_WORKFLOWS:
        blockers.append("unsupported_workflow")
    if bool(route_decision.needs_clarification):
        blockers.append("clarification_required")
    if not bool(route_decision.needs_products or route_decision.needs_knowledge):
        blockers.append("no_tool_capability_requested")
    if route_supported and not tool_suitable:
        blockers.append("tool_not_suitable")
    return tuple(blockers)


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
    tool_first_candidate = bool(route_supports_agentic and tool_suitable)
    selection_blockers = _agentic_selection_blockers(
        route_decision=route_decision,
        feature_enabled=feature_enabled,
        channel_allowed=channel_allowed,
        route_supported=route_supports_agentic,
        tool_suitable=tool_suitable,
    )

    if feature_enabled and channel_allowed and route_supports_agentic and tool_suitable:
        execution_mode = "agentic"
        selection_source = "agentic"
        selection_blockers = ()

    execution_decision = routing_policy.ExecutionDecision(
        route_decision=route_decision,
        execution_mode=execution_mode,
        reason=str(understanding.reason or internal_workflow or public_workflow),
        feature_enabled=feature_enabled,
        channel_allowed=channel_allowed,
        tool_suitable=tool_suitable,
        route_supported=route_supports_agentic,
        tool_first_candidate=tool_first_candidate,
        selection_blockers=selection_blockers,
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
