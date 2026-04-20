from __future__ import annotations

from dataclasses import replace
from typing import Optional

from app.services.chat.components.types import ComponentSource
from app.services.chat.routing import routing_policy
from app.services.chat.routing.contracts import DecisionState, UnderstandingResult
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities, build_chat_runtime_capabilities


def _project_public_workflow(internal_workflow: str) -> str:
    if internal_workflow in {"catalog_search", "product_detail", "mixed"}:
        return "catalog"
    if internal_workflow in {"company_info", "policy_info"}:
        return "knowledge"
    if internal_workflow in {"smalltalk", "off_topic"}:
        return "off_topic"
    return "fallback"


def _source_for_public_workflow(public_workflow: str) -> ComponentSource:
    if public_workflow == "catalog":
        return ComponentSource.SQL
    if public_workflow == "knowledge":
        return ComponentSource.KNOWLEDGE
    return ComponentSource.ERROR


def _build_route_decision(understanding: UnderstandingResult) -> routing_policy.WorkflowDecision:
    internal_workflow = str(understanding.workflow_hypothesis or "").strip().lower()
    public_workflow = _project_public_workflow(internal_workflow)
    if public_workflow == "fallback":
        reason = "routing_fallback"
        if not str(understanding.failure_reason or "").strip():
            reason = str(understanding.reason or "clarify")
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
    needs_knowledge = bool(understanding.needs_knowledge or public_workflow == "knowledge" or internal_workflow == "mixed")
    needs_clarification = bool(internal_workflow == "clarify")
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
        store_overview_request=bool(understanding.store_overview_request),
        knowledge_query=str(understanding.knowledge_query or "").strip() if needs_knowledge else "",
        reason=str(understanding.reason or internal_workflow or public_workflow),
        confidence=float(understanding.intent_confidence or 0.0),
    )


def build_decision_state(
    *,
    understanding: UnderstandingResult,
    user_text: str,
    channel: Optional[str],
    capabilities: ChatRuntimeCapabilities | None = None,
) -> DecisionState:
    caps = capabilities or build_chat_runtime_capabilities()
    internal_workflow = str(understanding.workflow_hypothesis or "clarify").strip().lower()
    route_decision = _build_route_decision(understanding)
    public_workflow = route_decision.workflow

    execution_mode = "component"
    selection_source = str(understanding.debug.get("understanding_source") or "staged_understanding")
    feature_enabled = bool(caps.agentic_function_calling_enabled)
    channel_allowed = routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps)
    sku_token = str((understanding.sku_tokens or [None])[0] or "")
    tool_suitable = routing_policy.is_agentic_tool_suitable(
        user_text=user_text,
        workflow=public_workflow,
        sku_token=sku_token or None,
        needs_products=route_decision.needs_products,
        needs_knowledge=route_decision.needs_knowledge,
    )

    if public_workflow != "fallback" and feature_enabled and channel_allowed and tool_suitable:
        execution_mode = "agentic"
        selection_source = "staged_agentic"

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
    if execution_mode == "agentic" and public_workflow == "fallback":
        execution_decision = replace(
            execution_decision,
            execution_mode="component",
            selection_source="staged_understanding",
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
        route_decision=route_decision,
        execution_decision=execution_decision,
        debug={
            "understanding_source": str(understanding.debug.get("understanding_source") or ""),
            "understanding_reason": str(understanding.reason or ""),
            "understanding_failure_reason": str(understanding.failure_reason or ""),
            "internal_workflow": internal_workflow,
        },
    )
