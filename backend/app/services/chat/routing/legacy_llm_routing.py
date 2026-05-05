from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, Dict, Sequence

from app.core.config import settings
from app.prompts.routing import routing_decision_prompt
from app.services.ai.llm_service import llm_service
from app.services.chat.routing import routing_policy
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities, build_chat_runtime_capabilities


def _coerce_execution_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in routing_policy.SUPPORTED_EXECUTION_MODES:
        return mode
    return "component"


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "True", "yes", "on"):
        return True
    if value in (0, "0", "false", "False", "no", "off"):
        return False
    return bool(default)


def _default_flags_for_workflow(workflow: str) -> tuple[bool, bool, bool]:
    if workflow == "catalog":
        return True, False, False
    if workflow == "knowledge":
        return False, True, False
    if workflow == "general_talking":
        return False, False, False
    if workflow == "off_topic":
        return False, False, False
    if workflow == "fallback":
        return False, False, True
    return False, False, False


def _fallback_workflow_decision(*, reason: str, confidence: float = 0.0) -> routing_policy.WorkflowDecision:
    return routing_policy.WorkflowDecision(
        workflow="fallback",
        source=routing_policy.ComponentSource.ERROR,
        needs_products=False,
        needs_knowledge=False,
        needs_clarification=True,
        store_overview_request=False,
        knowledge_query="",
        reason=reason,
        confidence=max(0.0, min(1.0, float(confidence))),
    )


def _timeout_guardrail_decision(
    *,
    text: str,
    detail_has_filters: bool,
    detail_request: bool,
    sku_tokens: Sequence[str],
) -> routing_policy.WorkflowDecision | None:
    text_norm = routing_policy.normalize_text(text)
    if not text_norm:
        return None
    if bool(sku_tokens) or detail_has_filters or detail_request:
        return routing_policy.WorkflowDecision(
            workflow="catalog",
            source=routing_policy.ComponentSource.SQL,
            needs_products=True,
            needs_knowledge=False,
            needs_clarification=False,
            store_overview_request=False,
            knowledge_query="",
            reason="routing_timeout_catalog_guardrail",
            confidence=0.51,
        )

    return None


def _should_soft_accept_llm_route(
    *,
    workflow: str,
    execution_mode: str,
    confidence: float,
    min_confidence: float,
    route_reason: str,
) -> bool:
    if execution_mode == "agentic":
        return False
    if workflow not in routing_policy.SUPPORTED_WORKFLOWS or workflow == "fallback":
        return False
    if confidence >= min_confidence:
        return False
    soft_floor = float(getattr(settings, "CHAT_LLM_ROUTING_SOFT_MIN_CONFIDENCE", 0.55))
    if confidence < soft_floor:
        return False
    if "unclear" in routing_policy.normalize_text(route_reason):
        return confidence >= soft_floor
    return True


def _coerce_llm_routing_payload(
    payload: Dict[str, Any],
) -> tuple[routing_policy.WorkflowDecision, str, str, float]:
    workflow = routing_policy._coerce_workflow(payload.get("workflow"))
    execution_mode = _coerce_execution_mode(payload.get("execution_mode"))
    defaults = _default_flags_for_workflow(workflow)
    needs_products = _coerce_bool(payload.get("needs_products"), default=defaults[0])
    needs_knowledge = _coerce_bool(payload.get("needs_knowledge"), default=defaults[1])
    needs_clarification = _coerce_bool(payload.get("needs_clarification"), default=defaults[2])
    store_overview_request = _coerce_bool(payload.get("store_overview_request"), default=False)
    knowledge_query = str(payload.get("knowledge_query") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    if workflow == "knowledge":
        needs_knowledge = True
    elif workflow == "catalog":
        needs_products = True
    elif workflow == "general_talking":
        needs_products = False
        needs_knowledge = False
        needs_clarification = False
    elif workflow == "off_topic":
        needs_products = False
        needs_knowledge = False
        needs_clarification = False
    elif workflow == "fallback":
        needs_clarification = True

    decision = routing_policy.WorkflowDecision(
        workflow=workflow,
        source=routing_policy._workflow_source(workflow),
        needs_products=needs_products,
        needs_knowledge=needs_knowledge,
        needs_clarification=needs_clarification,
        store_overview_request=store_overview_request,
        knowledge_query=knowledge_query if needs_knowledge else "",
        reason=reason,
        confidence=confidence,
    )
    return decision, execution_mode, reason, confidence


def _with_trace_fields(
    *,
    decision: routing_policy.ExecutionDecision,
    llm_route_decision: routing_policy.WorkflowDecision | None = None,
    llm_mode: str = "",
    llm_reason: str = "",
    llm_confidence: float = 0.0,
    selection_source: str = "",
    confidence_gate_applied: bool = False,
) -> routing_policy.ExecutionDecision:
    return replace(
        decision,
        selection_source=selection_source or decision.selection_source,
        llm_reason=llm_reason,
        llm_confidence=llm_confidence,
        llm_workflow=llm_route_decision.workflow if llm_route_decision else "",
        llm_execution_mode=llm_mode,
        confidence_gate_applied=confidence_gate_applied,
    )


def _confidence_gate_fallback_decision(
    *,
    caps: ChatRuntimeCapabilities,
    channel: str | None,
    llm_route_decision: routing_policy.WorkflowDecision,
    llm_mode: str,
    llm_reason: str,
    llm_confidence: float,
    decision_reason: str,
) -> routing_policy.ExecutionDecision:
    fallback = _fallback_workflow_decision(
        reason=llm_reason or decision_reason,
        confidence=llm_confidence,
    )
    decision = routing_policy.ExecutionDecision(
        route_decision=fallback,
        execution_mode="component",
        reason=decision_reason,
        feature_enabled=bool(caps.agentic_function_calling_enabled),
        channel_allowed=routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps),
        tool_suitable=False,
        selection_source="llm_fallback",
    )
    return _with_trace_fields(
        decision=decision,
        llm_route_decision=llm_route_decision,
        llm_mode=llm_mode,
        llm_reason=llm_reason or decision_reason,
        llm_confidence=llm_confidence,
        selection_source="llm_fallback",
        confidence_gate_applied=True,
    )


async def _llm_decide_routing(
    *,
    text: str,
    locale: str | None,
    channel: str | None,
    detail_has_filters: bool,
    detail_request: bool,
    sku_tokens: Sequence[str],
    compact_prompt: bool = False,
    timeout_ms: int | None = None,
    capabilities: ChatRuntimeCapabilities | None = None,
) -> Dict[str, Any]:
    caps = capabilities or build_chat_runtime_capabilities()
    model = str(caps.chat_llm_routing_model or "").strip()
    if not model:
        model = str(getattr(settings, "NLU_MODEL", "") or getattr(settings, "OPENAI_MODEL", ""))

    max_tokens = max(120, int(caps.chat_llm_routing_max_tokens))
    if compact_prompt:
        max_tokens = min(max_tokens, 140)
    temperature = float(caps.chat_llm_routing_temperature)
    system = routing_decision_prompt(compact_prompt=compact_prompt)
    user = (
        f"message={text}\n"
        f"locale={str(locale or '')}\n"
        f"channel={str(channel or '')}\n"
        f"detail_has_filters={bool(detail_has_filters)}\n"
        f"detail_request={bool(detail_request)}\n"
        f"sku_tokens={list(sku_tokens or [])}"
    )
    timeout_source_ms = timeout_ms
    if timeout_source_ms is None:
        timeout_source_ms = int(caps.chat_llm_routing_timeout_ms)
    timeout_seconds = max(0.2, float(timeout_source_ms) / 1000.0)
    return await asyncio.wait_for(
        llm_service.generate_chat_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort="minimal",
            usage_kind="routing_decision",
        ),
        timeout=timeout_seconds,
    )


async def decide_execution_mode_with_llm(
    *,
    text: str,
    channel: str | None,
    locale: str | None,
    detail_has_filters: bool,
    detail_request: bool,
    sku_tokens: Sequence[str],
    capabilities: ChatRuntimeCapabilities | None = None,
) -> routing_policy.ExecutionDecision:
    caps = capabilities or build_chat_runtime_capabilities()
    if not bool(caps.chat_llm_routing_enabled):
        fallback = _fallback_workflow_decision(reason="llm_routing_disabled")
        return routing_policy.ExecutionDecision(
            route_decision=fallback,
            execution_mode="component",
            reason="llm_routing_disabled",
            feature_enabled=bool(caps.agentic_function_calling_enabled),
            channel_allowed=routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps),
            tool_suitable=False,
            selection_source="llm_fallback",
        )
    if not str(text or "").strip():
        fallback = _fallback_workflow_decision(reason="empty_message")
        return routing_policy.ExecutionDecision(
            route_decision=fallback,
            execution_mode="component",
            reason="empty_message",
            feature_enabled=bool(caps.agentic_function_calling_enabled),
            channel_allowed=routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps),
            tool_suitable=False,
            selection_source="llm_fallback",
        )

    min_confidence = float(caps.chat_llm_routing_min_confidence)
    agentic_min_confidence = float(caps.chat_agentic_min_confidence)
    timeout_retry_enabled = bool(caps.chat_llm_routing_timeout_retry_enabled)
    timeout_retry_ms = max(300, int(caps.chat_llm_routing_timeout_retry_ms))
    timeout_retry_used = False

    llm_payload: Dict[str, Any] | None = None
    routing_error: Exception | None = None
    try:
        llm_payload = await _llm_decide_routing(
            text=text,
            locale=locale,
            channel=channel,
            detail_has_filters=detail_has_filters,
            detail_request=detail_request,
            sku_tokens=sku_tokens,
            capabilities=caps,
        )
    except asyncio.TimeoutError as exc:
        routing_error = exc
        if timeout_retry_enabled:
            try:
                llm_payload = await _llm_decide_routing(
                    text=text,
                    locale=locale,
                    channel=channel,
                    detail_has_filters=detail_has_filters,
                    detail_request=detail_request,
                    sku_tokens=sku_tokens,
                    compact_prompt=True,
                    timeout_ms=timeout_retry_ms,
                )
                timeout_retry_used = True
                routing_error = None
            except Exception as retry_exc:
                routing_error = retry_exc
    except Exception as exc:
        routing_error = exc

    if llm_payload is None:
        exc = routing_error or RuntimeError("routing_failed")
        timeout_guardrail = (
            _timeout_guardrail_decision(
                text=text,
                detail_has_filters=detail_has_filters,
                detail_request=detail_request,
                sku_tokens=sku_tokens,
            )
            if isinstance(exc, asyncio.TimeoutError)
            else None
        )
        if timeout_guardrail is not None:
            return _with_trace_fields(
                decision=routing_policy.ExecutionDecision(
                    route_decision=timeout_guardrail,
                    execution_mode="component",
                    reason="routing_timeout_guardrail",
                    feature_enabled=bool(caps.agentic_function_calling_enabled),
                    channel_allowed=routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps),
                    tool_suitable=False,
                    selection_source="llm_timeout_guardrail",
                    timeout_retry_used=timeout_retry_used,
                ),
                llm_reason=f"error:{type(exc).__name__}",
                llm_confidence=0.0,
                selection_source="llm_timeout_guardrail",
            )
        fallback = _fallback_workflow_decision(reason=f"routing_error:{type(exc).__name__}")
        return _with_trace_fields(
            decision=routing_policy.ExecutionDecision(
                route_decision=fallback,
                execution_mode="component",
                reason="routing_error",
                feature_enabled=bool(caps.agentic_function_calling_enabled),
                channel_allowed=routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps),
                tool_suitable=False,
                selection_source="llm_fallback",
                timeout_retry_used=timeout_retry_used,
            ),
            llm_reason=f"error:{type(exc).__name__}",
            llm_confidence=0.0,
            selection_source="llm_fallback",
        )

    if not isinstance(llm_payload, dict):
        fallback = _fallback_workflow_decision(reason="invalid_routing_payload")
        return _with_trace_fields(
            decision=routing_policy.ExecutionDecision(
                route_decision=fallback,
                execution_mode="component",
                reason="invalid_routing_payload",
                feature_enabled=bool(caps.agentic_function_calling_enabled),
                channel_allowed=routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps),
                tool_suitable=False,
                selection_source="llm_fallback",
            ),
            llm_reason="invalid_payload",
            llm_confidence=0.0,
            selection_source="llm_fallback",
        )

    llm_route_decision, llm_mode, llm_reason, llm_confidence = _coerce_llm_routing_payload(llm_payload)

    if _should_soft_accept_llm_route(
        workflow=llm_route_decision.workflow,
        execution_mode=llm_mode,
        confidence=llm_confidence,
        min_confidence=min_confidence,
        route_reason=llm_reason,
    ):
        decision = routing_policy.ExecutionDecision(
            route_decision=llm_route_decision,
            execution_mode=llm_mode,
            reason=llm_reason or "llm_selected_soft",
            feature_enabled=bool(caps.agentic_function_calling_enabled),
            channel_allowed=routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps),
            tool_suitable=routing_policy.is_agentic_tool_suitable(
                user_text=text,
                workflow=llm_route_decision.workflow,
                sku_token=str(sku_tokens[0]) if list(sku_tokens or []) else None,
                needs_products=llm_route_decision.needs_products,
                needs_knowledge=llm_route_decision.needs_knowledge,
            ),
            selection_source="llm_soft",
            timeout_retry_used=timeout_retry_used,
        )
        return _with_trace_fields(
            decision=decision,
            llm_route_decision=llm_route_decision,
            llm_mode=llm_mode,
            llm_reason=llm_reason,
            llm_confidence=llm_confidence,
            selection_source="llm_soft",
            confidence_gate_applied=True,
        )

    if llm_confidence < min_confidence:
        return _confidence_gate_fallback_decision(
            caps=caps,
            channel=channel,
            llm_route_decision=llm_route_decision,
            llm_mode=llm_mode,
            llm_reason=llm_reason,
            llm_confidence=llm_confidence,
            decision_reason="confidence_below_threshold",
        )

    if llm_mode == "agentic" and llm_confidence < agentic_min_confidence:
        return _confidence_gate_fallback_decision(
            caps=caps,
            channel=channel,
            llm_route_decision=llm_route_decision,
            llm_mode=llm_mode,
            llm_reason=llm_reason,
            llm_confidence=llm_confidence,
            decision_reason="agentic_confidence_below_threshold",
        )

    feature_enabled = bool(caps.agentic_function_calling_enabled)
    channel_allowed = routing_policy.is_agentic_channel_enabled(channel=channel, capabilities=caps)
    sku_token = str(sku_tokens[0]) if list(sku_tokens or []) else None
    tool_suitable = routing_policy.is_agentic_tool_suitable(
        user_text=text,
        workflow=llm_route_decision.workflow,
        sku_token=sku_token,
        needs_products=llm_route_decision.needs_products,
        needs_knowledge=llm_route_decision.needs_knowledge,
    )

    decision = routing_policy.ExecutionDecision(
        route_decision=llm_route_decision,
        execution_mode=llm_mode,
        reason=llm_reason or ("llm_selected_retry" if timeout_retry_used else "llm_selected"),
        feature_enabled=feature_enabled,
        channel_allowed=channel_allowed,
        tool_suitable=tool_suitable,
        selection_source="llm_retry" if timeout_retry_used else "llm",
        timeout_retry_used=timeout_retry_used,
    )
    decision = _with_trace_fields(
        decision=decision,
        llm_route_decision=llm_route_decision,
        llm_mode=llm_mode,
        llm_reason=llm_reason or ("retry_after_timeout" if timeout_retry_used else ""),
        llm_confidence=llm_confidence,
        selection_source=decision.selection_source,
    )

    if llm_mode != "agentic":
        return replace(decision, execution_mode="component")
    if not feature_enabled:
        return replace(decision, execution_mode="component", reason="feature_disabled", selection_source="llm_guardrail")
    if not channel_allowed:
        return replace(decision, execution_mode="component", reason="channel_not_allowed", selection_source="llm_guardrail")
    if not tool_suitable:
        return replace(decision, execution_mode="component", reason="tool_not_suitable", selection_source="llm_guardrail")
    return decision
