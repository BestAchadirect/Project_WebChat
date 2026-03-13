from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, Sequence

from app.core.config import settings
from app.schemas.chat import ChatRouting
from app.services.ai.llm_service import llm_service
from app.services.chat.components.types import ComponentSource

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
    shadow_mode: bool = False

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


def is_agentic_channel_enabled(*, channel: str | None) -> bool:
    if not bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)):
        return False
    allowed_raw = str(getattr(settings, "AGENTIC_ALLOWED_CHANNELS", "") or "")
    allowed = {part.strip().lower() for part in allowed_raw.split(",") if part.strip()}
    if not allowed:
        return True
    return str(channel or "").strip().lower() in allowed


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
    inventory_keywords = ("in stock", "inventory", "availability", "available", "stock")
    detail_keywords = ("details", "detail", "spec", "specs", "sku", "product code", "master code")
    if any(token in text for token in inventory_keywords):
        return True
    if any(token in text for token in detail_keywords):
        return True
    # Allow catalog+knowledge mixed questions to escalate only when concrete product data is needed.
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
        reason=reason,
        confidence=max(0.0, min(1.0, float(confidence))),
    )


def _coerce_llm_routing_payload(payload: Dict[str, Any]) -> tuple[WorkflowDecision, str, str, float]:
    workflow = _coerce_workflow(payload.get("workflow"))
    execution_mode = _coerce_execution_mode(payload.get("execution_mode"))
    defaults = _default_flags_for_workflow(workflow)
    needs_products = _coerce_bool(payload.get("needs_products"), default=defaults[0])
    needs_knowledge = _coerce_bool(payload.get("needs_knowledge"), default=defaults[1])
    needs_clarification = _coerce_bool(payload.get("needs_clarification"), default=defaults[2])
    store_overview_request = _coerce_bool(payload.get("store_overview_request"), default=False)
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
    shadow_mode: bool = False,
) -> ExecutionDecision:
    return replace(
        decision,
        selection_source=selection_source or decision.selection_source,
        llm_reason=llm_reason,
        llm_confidence=llm_confidence,
        llm_workflow=llm_route_decision.workflow if llm_route_decision else "",
        llm_execution_mode=llm_mode,
        confidence_gate_applied=confidence_gate_applied,
        shadow_mode=shadow_mode,
    )


async def _llm_decide_routing(
    *,
    text: str,
    locale: str | None,
    channel: str | None,
    detail_has_filters: bool,
    detail_request: bool,
    sku_tokens: Sequence[str],
) -> Dict[str, Any]:
    model = str(getattr(settings, "CHAT_LLM_ROUTING_MODEL", "") or "").strip()
    if not model:
        model = str(getattr(settings, "NLU_MODEL", "") or getattr(settings, "OPENAI_MODEL", ""))

    max_tokens = max(120, int(getattr(settings, "CHAT_LLM_ROUTING_MAX_TOKENS", 180)))
    temperature = float(getattr(settings, "CHAT_LLM_ROUTING_TEMPERATURE", 0.0))
    system = (
        "Return ONLY strict JSON with keys: workflow, execution_mode, needs_products, needs_knowledge, "
        "needs_clarification, store_overview_request, reason, confidence.\n"
        "workflow must be one of: catalog, knowledge, recommendation, smalltalk, off_topic, fallback.\n"
        "execution_mode must be one of: component, agentic.\n"
        "Routing rules:\n"
        "- Use knowledge for company info, about us, store overview, contact details, sales contact, support, "
        "location, buy in person, shipping, refund, payment, warranty, and other policy/help questions.\n"
        "- Use catalog for product browsing, product discovery, filters, materials, colors, gauges, and general "
        "shopping requests.\n"
        "- Use recommendation when the user asks for suggestions, ideas, or recommendations, even if the request "
        "is broad.\n"
        "- Use smalltalk only for greetings, thanks, or casual non-business chat.\n"
        "- Use off_topic for requests unrelated to shopping, product support, or store policies (e.g., coding help, "
        "general AI tasks, unrelated trivia, non-store personal tasks).\n"
        "- Use fallback only when the request is too unclear to answer safely.\n"
        "Additional rules:\n"
        "- If the request asks about buying in person, company/store location, sales team, or contact channels, "
        "set needs_knowledge=true.\n"
        "- If the request asks for suggestions without enough detail, prefer workflow=recommendation with "
        "needs_clarification=true instead of fallback.\n"
        "- If the request mixes shopping and policy/help, choose the main workflow owner and use flags to "
        "represent both needs.\n"
        "- Use store_overview_request=true only when the user is asking about the company/store/business itself.\n"
        "- Use execution_mode=agentic only for concrete multi-step tool use such as SKU validation, inventory "
        "checks, or chained product detail lookups.\n"
        "- If uncertain, prefer the closest business workflow over smalltalk.\n"
        "- Do not classify company/store/contact/location questions as smalltalk.\n"
        "- If user asks for coding/programming or asks what you are as a general AI assistant outside store context, "
        "prefer off_topic.\n"
        "Confidence rules:\n"
        "- Use high confidence (0.8-1.0) when the request is clear.\n"
        "- Use medium confidence (0.5-0.79) when the request is understandable but broad.\n"
        "- Use low confidence (<0.5) only when the request is genuinely unclear.\n"
        "Examples:\n"
        'User: "what is your company?"\n'
        'Output: {"workflow":"knowledge","execution_mode":"component","needs_products":false,'
        '"needs_knowledge":true,"needs_clarification":false,"store_overview_request":true,'
        '"reason":"User is asking about the company or business.","confidence":0.9}\n'
        'User: "where is your company? I want to buy in person"\n'
        'Output: {"workflow":"knowledge","execution_mode":"component","needs_products":false,'
        '"needs_knowledge":true,"needs_clarification":true,"store_overview_request":true,'
        '"reason":"User is asking for company or store location and in-person buying information.",'
        '"confidence":0.86}\n'
        'User: "how can I contact your sales team?"\n'
        'Output: {"workflow":"knowledge","execution_mode":"component","needs_products":false,'
        '"needs_knowledge":true,"needs_clarification":false,"store_overview_request":true,'
        '"reason":"User is asking for sales contact information.","confidence":0.95}\n'
        'User: "Do you have any product suggest?"\n'
        'Output: {"workflow":"recommendation","execution_mode":"component","needs_products":true,'
        '"needs_knowledge":false,"needs_clarification":true,"store_overview_request":false,'
        '"reason":"User is asking for product suggestions but has not given enough preferences.",'
        '"confidence":0.83}\n'
        'User: "Suggest something in titanium"\n'
        'Output: {"workflow":"recommendation","execution_mode":"component","needs_products":true,'
        '"needs_knowledge":false,"needs_clarification":false,"store_overview_request":false,'
        '"reason":"User wants product recommendations with a material preference.","confidence":0.92}\n'
        'User: "Show me opal rings and how can I contact you?"\n'
        'Output: {"workflow":"catalog","execution_mode":"component","needs_products":true,'
        '"needs_knowledge":true,"needs_clarification":false,"store_overview_request":false,'
        '"reason":"Primary request is product browsing with a secondary contact need.","confidence":0.9}\n'
        'User: "Do you have ABC-1 in stock?"\n'
        'Output: {"workflow":"catalog","execution_mode":"agentic","needs_products":true,'
        '"needs_knowledge":false,"needs_clarification":false,"store_overview_request":false,'
        '"reason":"User wants a concrete inventory lookup for a specific SKU.","confidence":0.96}\n'
        'User: "hi"\n'
        'Output: {"workflow":"smalltalk","execution_mode":"component","needs_products":false,'
        '"needs_knowledge":false,"needs_clarification":false,"store_overview_request":false,'
        '"reason":"Greeting only.","confidence":0.98}\n'
        'User: "Can you do coding. and who are you? are you an ai?"\n'
        'Output: {"workflow":"off_topic","execution_mode":"component","needs_products":false,'
        '"needs_knowledge":false,"needs_clarification":false,"store_overview_request":false,'
        '"reason":"The request is unrelated to store shopping/support and asks for general AI/coding capability.",'
        '"confidence":0.92}'
    )
    user = (
        f"message={text}\n"
        f"locale={str(locale or '')}\n"
        f"channel={str(channel or '')}\n"
        f"detail_has_filters={bool(detail_has_filters)}\n"
        f"detail_request={bool(detail_request)}\n"
        f"sku_tokens={list(sku_tokens or [])}"
    )
    timeout_seconds = max(0.2, float(getattr(settings, "CHAT_LLM_ROUTING_TIMEOUT_MS", 1200)) / 1000.0)
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
) -> ExecutionDecision:
    if not bool(getattr(settings, "CHAT_LLM_ROUTING_ENABLED", False)):
        fallback = _fallback_workflow_decision(reason="llm_routing_disabled")
        return ExecutionDecision(
            route_decision=fallback,
            execution_mode="component",
            reason="llm_routing_disabled",
            feature_enabled=bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)),
            channel_allowed=is_agentic_channel_enabled(channel=channel),
            tool_suitable=False,
            selection_source="llm_fallback",
        )
    if not str(text or "").strip():
        fallback = _fallback_workflow_decision(reason="empty_message")
        return ExecutionDecision(
            route_decision=fallback,
            execution_mode="component",
            reason="empty_message",
            feature_enabled=bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)),
            channel_allowed=is_agentic_channel_enabled(channel=channel),
            tool_suitable=False,
            selection_source="llm_fallback",
        )

    shadow_mode = bool(getattr(settings, "CHAT_LLM_ROUTING_SHADOW_MODE", False))
    min_confidence = float(getattr(settings, "CHAT_LLM_ROUTING_MIN_CONFIDENCE", 0.7))
    agentic_min_confidence = float(getattr(settings, "CHAT_AGENTIC_MIN_CONFIDENCE", 0.8))

    try:
        llm_payload = await _llm_decide_routing(
            text=text,
            locale=locale,
            channel=channel,
            detail_has_filters=detail_has_filters,
            detail_request=detail_request,
            sku_tokens=sku_tokens,
        )
    except Exception as exc:
        fallback = _fallback_workflow_decision(reason=f"routing_error:{type(exc).__name__}")
        return _with_trace_fields(
            decision=ExecutionDecision(
                route_decision=fallback,
                execution_mode="component",
                reason="routing_error",
                feature_enabled=bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)),
                channel_allowed=is_agentic_channel_enabled(channel=channel),
                tool_suitable=False,
                selection_source="llm_fallback",
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
                feature_enabled=bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)),
                channel_allowed=is_agentic_channel_enabled(channel=channel),
                tool_suitable=False,
                selection_source="llm_fallback",
            ),
            llm_reason="invalid_payload",
            llm_confidence=0.0,
            selection_source="llm_fallback",
        )

    llm_route_decision, llm_mode, llm_reason, llm_confidence = _coerce_llm_routing_payload(llm_payload)

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
                feature_enabled=bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)),
                channel_allowed=is_agentic_channel_enabled(channel=channel),
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
                feature_enabled=bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)),
                channel_allowed=is_agentic_channel_enabled(channel=channel),
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

    feature_enabled = bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False))
    channel_allowed = is_agentic_channel_enabled(channel=channel)
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
        reason=llm_reason or "llm_selected",
        feature_enabled=feature_enabled,
        channel_allowed=channel_allowed,
        tool_suitable=tool_suitable,
        selection_source="llm_shadow" if shadow_mode else "llm",
    )
    decision = _with_trace_fields(
        decision=decision,
        llm_route_decision=llm_route_decision,
        llm_mode=llm_mode,
        llm_reason=llm_reason,
        llm_confidence=llm_confidence,
        selection_source="llm_shadow" if shadow_mode else "llm",
        shadow_mode=shadow_mode,
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
