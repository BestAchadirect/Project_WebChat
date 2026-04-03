from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, Sequence

from app.core.config import settings
from app.prompts.routing import routing_decision_prompt
from app.schemas.chat import ChatRouting
from app.services.ai.llm_service import llm_service
from app.services.chat.components.types import ComponentSource
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities, build_chat_runtime_capabilities

SUPPORTED_WORKFLOWS = {
    "catalog",
    "knowledge",
    "recommendation",
    "smalltalk",
    "off_topic",
    "fallback",
}
SUPPORTED_EXECUTION_MODES = {"component", "agentic"}
AGENTIC_SUPPORTED_WORKFLOWS = {"catalog", "knowledge"}

@dataclass(frozen=True)
class WorkflowDecision:
    workflow: str
    source: ComponentSource
    needs_products: bool
    needs_knowledge: bool
    needs_clarification: bool
    store_overview_request: bool
    recommendation_mode_requested: str = "similar_items"
    knowledge_query: str = ""
    reason: str = ""
    confidence: float = 0.0

    def to_public_routing(self, *, execution_mode: str, selection_source: str) -> ChatRouting:
        return ChatRouting(
            workflow=self.workflow,
            execution_mode=execution_mode,
            needs_products=self.needs_products,
            needs_knowledge=self.needs_knowledge,
            needs_clarification=self.needs_clarification,
            store_overview_request=self.store_overview_request,
            recommendation_mode_requested=self.recommendation_mode_requested,
            reason=self.reason,
            confidence=self.confidence,
            selection_source=selection_source,
        )


@dataclass(frozen=True)
class ExecutionDecision:
    route_decision: WorkflowDecision
    execution_mode: str
    reason: str
    feature_enabled: bool
    channel_allowed: bool
    tool_suitable: bool
    selection_source: str = "llm_fallback"
    llm_reason: str = ""
    llm_confidence: float = 0.0
    llm_workflow: str = ""
    llm_execution_mode: str = ""
    confidence_gate_applied: bool = False
    timeout_retry_used: bool = False

    def to_public_routing(self) -> ChatRouting:
        return self.route_decision.to_public_routing(
            execution_mode=self.execution_mode,
            selection_source=self.selection_source,
        )


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def is_probable_sku_token(token: str) -> bool:
    cleaned = (token or "").strip().strip(".,!?;:'\"()[]{}<>")
    if not cleaned:
        return False
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,31}", cleaned):
        return False
    has_alpha = any(ch.isalpha() for ch in cleaned)
    has_digit = any(ch.isdigit() for ch in cleaned)
    if not has_alpha:
        return False
    if has_digit:
        return True
    return cleaned == cleaned.upper() and any(ch in "._-" for ch in cleaned)


def extract_sku_tokens(text: str) -> list[str]:
    pattern = r"\b[A-Za-z0-9]{2,}(?:[-._][A-Za-z0-9]{1,})+\b"
    found = re.findall(pattern, str(text or ""))
    deduped: list[str] = []
    seen = set()
    for token in found:
        if not is_probable_sku_token(token):
            continue
        key = token.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(token)
    return deduped


def is_agentic_channel_enabled(
    *,
    channel: str | None,
    capabilities: ChatRuntimeCapabilities | None = None,
) -> bool:
    caps = capabilities or build_chat_runtime_capabilities()
    return bool(caps.is_agentic_channel_enabled(channel=channel))


def is_agentic_tool_suitable(
    *,
    user_text: str,
    workflow: str,
    sku_token: str | None,
    needs_products: bool = False,
    needs_knowledge: bool = False,
) -> bool:
    text = normalize_text(user_text)
    if not text:
        return False
    if workflow not in AGENTIC_SUPPORTED_WORKFLOWS:
        return False
    if sku_token:
        return True
    # Let the LLM decide agentic routing for broad catalog+knowledge chains.
    return bool(workflow == "catalog" and needs_products and needs_knowledge)


def _workflow_source(workflow: str) -> ComponentSource:
    if workflow == "knowledge":
        return ComponentSource.KNOWLEDGE
    if workflow == "smalltalk":
        return ComponentSource.TOOL
    if workflow == "off_topic":
        return ComponentSource.ERROR
    if workflow == "fallback":
        return ComponentSource.ERROR
    return ComponentSource.SQL


def _coerce_workflow(value: Any) -> str:
    workflow = str(value or "").strip().lower()
    if workflow in SUPPORTED_WORKFLOWS:
        return workflow
    return "fallback"


def _coerce_execution_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in SUPPORTED_EXECUTION_MODES:
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
    if workflow in {"catalog", "recommendation"}:
        return True, False, False
    if workflow == "knowledge":
        return False, True, False
    if workflow == "off_topic":
        return False, False, False
    if workflow == "fallback":
        return False, False, True
    return False, False, False


def _fallback_workflow_decision(*, reason: str, confidence: float = 0.0) -> WorkflowDecision:
    return WorkflowDecision(
        workflow="fallback",
        source=ComponentSource.ERROR,
        needs_products=False,
        needs_knowledge=False,
        needs_clarification=True,
        store_overview_request=False,
        recommendation_mode_requested="similar_items",
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
) -> WorkflowDecision | None:
    text_norm = normalize_text(text)
    if not text_norm:
        return None
    if bool(sku_tokens) or detail_has_filters or detail_request:
        return WorkflowDecision(
            workflow="catalog",
            source=ComponentSource.SQL,
            needs_products=True,
            needs_knowledge=False,
            needs_clarification=False,
            store_overview_request=False,
            recommendation_mode_requested="similar_items",
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
    if workflow not in SUPPORTED_WORKFLOWS or workflow == "fallback":
        return False
    if confidence >= min_confidence:
        return False
    soft_floor = float(getattr(settings, "CHAT_LLM_ROUTING_SOFT_MIN_CONFIDENCE", 0.55))
    if confidence < soft_floor:
        return False
    if "unclear" in normalize_text(route_reason):
        # Preserve the structured clarification path only when the model is
        # explicitly signaling ambiguity and the confidence is genuinely low.
        return confidence >= soft_floor
    return True


def _promote_directional_fallback_route(
    *,
    text: str,
    route_reason: str,
    llm_route_decision: WorkflowDecision,
    detail_has_filters: bool,
    detail_request: bool,
    sku_tokens: Sequence[str],
) -> WorkflowDecision | None:
    if llm_route_decision.workflow != "fallback":
        return None

    soft_floor = float(getattr(settings, "CHAT_LLM_ROUTING_SOFT_MIN_CONFIDENCE", 0.55))
    if llm_route_decision.confidence < soft_floor:
        return None

    normalized_text = normalize_text(text)
    normalized_reason = normalize_text(route_reason)
    combined_text = f"{normalized_text} {normalized_reason}".strip()
    if not combined_text:
        return None

    recommendation_cues = (
        "recommend",
        "suggest",
        "what goes with",
        "what fits",
        "matching",
        "complementary",
        "pair",
        "pairs with",
    )
    knowledge_cues = (
        "shipping",
        "refund",
        "payment",
        "contact",
        "location",
        "showroom",
        "address",
        "phone",
        "email",
        "warranty",
        "policy",
        "hours",
        "open",
        "close",
    )
    shopping_cues = (
        "show me",
        "do you have",
        "have any",
        "something",
        "looking for",
        "find",
        "elegant",
        "nice",
        "jewelry",
        "product",
        "material",
        "color",
        "gauge",
        "design",
        "style",
        "helix",
        "labret",
        "titanium",
        "opal",
        "barbell",
    )

    product_signal = bool(detail_has_filters or detail_request or sku_tokens)
    recommendation_signal = bool(
        llm_route_decision.recommendation_mode_requested == "complementary_items"
        or any(cue in combined_text for cue in recommendation_cues)
    )
    knowledge_signal = bool(
        llm_route_decision.needs_knowledge
        or llm_route_decision.store_overview_request
        or any(cue in combined_text for cue in knowledge_cues)
    )
    shopping_signal = bool(product_signal or llm_route_decision.needs_products or any(cue in combined_text for cue in shopping_cues))

    if recommendation_signal and shopping_signal:
        workflow = "recommendation"
    elif shopping_signal and knowledge_signal:
        workflow = "catalog"
    elif recommendation_signal:
        workflow = "recommendation"
    elif shopping_signal:
        workflow = "catalog"
    elif knowledge_signal:
        workflow = "knowledge"
    else:
        return None

    needs_products = workflow in {"catalog", "recommendation"}
    needs_knowledge = workflow == "knowledge" or (workflow == "catalog" and bool(llm_route_decision.needs_knowledge))
    return WorkflowDecision(
        workflow=workflow,
        source=_workflow_source(workflow),
        needs_products=needs_products,
        needs_knowledge=needs_knowledge,
        needs_clarification=False,
        store_overview_request=bool(llm_route_decision.store_overview_request if workflow == "knowledge" else False),
        recommendation_mode_requested=(
            "complementary_items"
            if workflow == "recommendation" and recommendation_signal
            else "similar_items"
        ),
        knowledge_query=str(llm_route_decision.knowledge_query or "").strip() if needs_knowledge else "",
        reason=str(llm_route_decision.reason or "").strip(),
        confidence=float(llm_route_decision.confidence or 0.0),
    )


def _coerce_llm_routing_payload(payload: Dict[str, Any]) -> tuple[WorkflowDecision, str, str, float]:
    workflow = _coerce_workflow(payload.get("workflow"))
    execution_mode = _coerce_execution_mode(payload.get("execution_mode"))
    defaults = _default_flags_for_workflow(workflow)
    needs_products = _coerce_bool(payload.get("needs_products"), default=defaults[0])
    needs_knowledge = _coerce_bool(payload.get("needs_knowledge"), default=defaults[1])
    needs_clarification = _coerce_bool(payload.get("needs_clarification"), default=defaults[2])
    store_overview_request = _coerce_bool(payload.get("store_overview_request"), default=False)
    recommendation_mode_requested = str(payload.get("recommendation_mode_requested") or "similar_items").strip().lower()
    if recommendation_mode_requested not in {"similar_items", "complementary_items"}:
        recommendation_mode_requested = "similar_items"
    knowledge_query = str(payload.get("knowledge_query") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    if workflow == "recommendation":
        needs_products = True
        needs_knowledge = False
    elif workflow == "knowledge":
        needs_knowledge = True
    elif workflow == "catalog":
        needs_products = True
    elif workflow == "smalltalk":
        needs_products = False
        needs_knowledge = False
    elif workflow == "off_topic":
        needs_products = False
        needs_knowledge = False
        needs_clarification = False
    elif workflow == "fallback":
        needs_clarification = True

    decision = WorkflowDecision(
        workflow=workflow,
        source=_workflow_source(workflow),
        needs_products=needs_products,
        needs_knowledge=needs_knowledge,
        needs_clarification=needs_clarification,
        store_overview_request=store_overview_request,
        recommendation_mode_requested=recommendation_mode_requested if workflow == "recommendation" else "similar_items",
        knowledge_query=knowledge_query if needs_knowledge else "",
        reason=reason,
        confidence=confidence,
    )
    return decision, execution_mode, reason, confidence


def _with_trace_fields(
    *,
    decision: ExecutionDecision,
    llm_route_decision: WorkflowDecision | None = None,
    llm_mode: str = "",
    llm_reason: str = "",
    llm_confidence: float = 0.0,
    selection_source: str = "",
    confidence_gate_applied: bool = False,
) -> ExecutionDecision:
    return replace(
        decision,
        selection_source=selection_source or decision.selection_source,
        llm_reason=llm_reason,
        llm_confidence=llm_confidence,
        llm_workflow=llm_route_decision.workflow if llm_route_decision else "",
        llm_execution_mode=llm_mode,
        confidence_gate_applied=confidence_gate_applied,
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
) -> ExecutionDecision:
    caps = capabilities or build_chat_runtime_capabilities()
    if not bool(caps.chat_llm_routing_enabled):
        fallback = _fallback_workflow_decision(reason="llm_routing_disabled")
        return ExecutionDecision(
            route_decision=fallback,
            execution_mode="component",
            reason="llm_routing_disabled",
            feature_enabled=bool(caps.agentic_function_calling_enabled),
            channel_allowed=is_agentic_channel_enabled(channel=channel, capabilities=caps),
            tool_suitable=False,
            selection_source="llm_fallback",
        )
    if not str(text or "").strip():
        fallback = _fallback_workflow_decision(reason="empty_message")
        return ExecutionDecision(
            route_decision=fallback,
            execution_mode="component",
            reason="empty_message",
            feature_enabled=bool(caps.agentic_function_calling_enabled),
            channel_allowed=is_agentic_channel_enabled(channel=channel, capabilities=caps),
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
                decision=ExecutionDecision(
                    route_decision=timeout_guardrail,
                    execution_mode="component",
                    reason="routing_timeout_guardrail",
                    feature_enabled=bool(caps.agentic_function_calling_enabled),
                    channel_allowed=is_agentic_channel_enabled(channel=channel, capabilities=caps),
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
            decision=ExecutionDecision(
                route_decision=fallback,
                execution_mode="component",
                reason="routing_error",
                feature_enabled=bool(caps.agentic_function_calling_enabled),
                channel_allowed=is_agentic_channel_enabled(channel=channel, capabilities=caps),
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
            decision=ExecutionDecision(
                route_decision=fallback,
                execution_mode="component",
                reason="invalid_routing_payload",
                feature_enabled=bool(caps.agentic_function_calling_enabled),
                channel_allowed=is_agentic_channel_enabled(channel=channel, capabilities=caps),
                tool_suitable=False,
                selection_source="llm_fallback",
            ),
            llm_reason="invalid_payload",
            llm_confidence=0.0,
            selection_source="llm_fallback",
        )

    llm_route_decision, llm_mode, llm_reason, llm_confidence = _coerce_llm_routing_payload(llm_payload)

    promoted_route_decision = _promote_directional_fallback_route(
        text=text,
        route_reason=llm_reason,
        llm_route_decision=llm_route_decision,
        detail_has_filters=detail_has_filters,
        detail_request=detail_request,
        sku_tokens=sku_tokens,
    )
    if promoted_route_decision is not None:
        decision = ExecutionDecision(
            route_decision=promoted_route_decision,
            execution_mode=llm_mode,
            reason=llm_reason or "llm_selected_soft",
            feature_enabled=bool(caps.agentic_function_calling_enabled),
            channel_allowed=is_agentic_channel_enabled(channel=channel, capabilities=caps),
            tool_suitable=is_agentic_tool_suitable(
                user_text=text,
                workflow=promoted_route_decision.workflow,
                sku_token=str(sku_tokens[0]) if list(sku_tokens or []) else None,
                needs_products=promoted_route_decision.needs_products,
                needs_knowledge=promoted_route_decision.needs_knowledge,
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

    if _should_soft_accept_llm_route(
        workflow=llm_route_decision.workflow,
        execution_mode=llm_mode,
        confidence=llm_confidence,
        min_confidence=min_confidence,
        route_reason=llm_reason,
    ):
        decision = ExecutionDecision(
            route_decision=llm_route_decision,
            execution_mode=llm_mode,
            reason=llm_reason or "llm_selected_soft",
            feature_enabled=bool(caps.agentic_function_calling_enabled),
            channel_allowed=is_agentic_channel_enabled(channel=channel, capabilities=caps),
            tool_suitable=is_agentic_tool_suitable(
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
        fallback = _fallback_workflow_decision(
            reason=llm_reason or "confidence_below_threshold",
            confidence=llm_confidence,
        )
        return _with_trace_fields(
            decision=ExecutionDecision(
                route_decision=fallback,
                execution_mode="component",
                reason="confidence_below_threshold",
                feature_enabled=bool(caps.agentic_function_calling_enabled),
                channel_allowed=is_agentic_channel_enabled(channel=channel, capabilities=caps),
                tool_suitable=False,
                selection_source="llm_fallback",
            ),
            llm_route_decision=llm_route_decision,
            llm_mode=llm_mode,
            llm_reason=llm_reason or "confidence_below_threshold",
            llm_confidence=llm_confidence,
            selection_source="llm_fallback",
            confidence_gate_applied=True,
        )

    if llm_mode == "agentic" and llm_confidence < agentic_min_confidence:
        fallback = _fallback_workflow_decision(
            reason=llm_reason or "agentic_confidence_below_threshold",
            confidence=llm_confidence,
        )
        return _with_trace_fields(
            decision=ExecutionDecision(
                route_decision=fallback,
                execution_mode="component",
                reason="agentic_confidence_below_threshold",
                feature_enabled=bool(caps.agentic_function_calling_enabled),
                channel_allowed=is_agentic_channel_enabled(channel=channel, capabilities=caps),
                tool_suitable=False,
                selection_source="llm_fallback",
            ),
            llm_route_decision=llm_route_decision,
            llm_mode=llm_mode,
            llm_reason=llm_reason or "agentic_confidence_below_threshold",
            llm_confidence=llm_confidence,
            selection_source="llm_fallback",
            confidence_gate_applied=True,
        )

    feature_enabled = bool(caps.agentic_function_calling_enabled)
    channel_allowed = is_agentic_channel_enabled(channel=channel, capabilities=caps)
    sku_token = str(sku_tokens[0]) if list(sku_tokens or []) else None
    tool_suitable = is_agentic_tool_suitable(
        user_text=text,
        workflow=llm_route_decision.workflow,
        sku_token=sku_token,
        needs_products=llm_route_decision.needs_products,
        needs_knowledge=llm_route_decision.needs_knowledge,
    )

    decision = ExecutionDecision(
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
