from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from app.schemas.chat import ChatRouting
from app.services.chat.components.types import ComponentSource
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities, build_chat_runtime_capabilities

SUPPORTED_WORKFLOWS = {
    "catalog",
    "knowledge",
    "general_talking",
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
    knowledge_query: str = ""
    reason: str = ""
    confidence: float = 0.0

    def to_public_routing(self, *, execution_mode: str, selection_source: str) -> ChatRouting:
        return ChatRouting(
            workflow=_coerce_workflow(self.workflow),
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
    timeout_retry_used: bool = False

    def to_public_routing(self) -> ChatRouting:
        return self.route_decision.to_public_routing(
            execution_mode=self.execution_mode,
            selection_source=self.selection_source,
        )


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def is_probable_sku_token(token: str, *, allow_lowercase_alpha_only: bool = False) -> bool:
    cleaned = (token or "").strip().strip(".,!?;:'\"()[]{}<>")
    if not cleaned:
        return False
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,31}", cleaned):
        return False
    if re.fullmatch(r"\d{1,2}g(?:auge)?", cleaned.lower()):
        return False
    has_alpha = any(ch.isalpha() for ch in cleaned)
    has_digit = any(ch.isdigit() for ch in cleaned)
    if not has_alpha:
        return False
    if has_digit:
        return True
    if cleaned.isalpha() and cleaned == cleaned.upper() and len(cleaned) >= 4:
        return True
    if allow_lowercase_alpha_only and cleaned.isalpha() and cleaned.islower() and len(cleaned) >= 4:
        return True
    return cleaned == cleaned.upper() and any(ch in "._-" for ch in cleaned)


def extract_sku_tokens(text: str) -> list[str]:
    raw_text = str(text or "")
    explicit_code_pattern = re.compile(
        r"\b(?P<marker>sku|master\s+code|product\s+code|style\s+code|code|style)\s*[:#-]?\s*"
        r"(?P<token>[A-Za-z0-9][A-Za-z0-9._-]{1,31})\b",
        flags=re.IGNORECASE,
    )
    separated_code_pattern = r"\b[A-Za-z0-9]{2,}(?:[-._][A-Za-z0-9]{1,})+\b"
    compact_master_pattern = r"\b[A-Za-z]{2,}[A-Za-z0-9]*\d[A-Za-z0-9._-]*\b"
    found: list[tuple[str, bool]] = []
    for match in explicit_code_pattern.finditer(raw_text):
        marker = str(match.group("marker") or "").strip().lower()
        token = str(match.group("token") or "").strip()
        found.append((token, True if marker else False))
    found.extend((token, False) for token in re.findall(separated_code_pattern, raw_text))
    found.extend((token, False) for token in re.findall(compact_master_pattern, raw_text))
    deduped: list[str] = []
    seen = set()
    for token, is_explicit in found:
        if not is_probable_sku_token(token, allow_lowercase_alpha_only=is_explicit):
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
    clean_workflow = _coerce_workflow(workflow)
    capability_requested = bool(needs_products or needs_knowledge or sku_token)
    if not capability_requested:
        return False
    if clean_workflow not in AGENTIC_SUPPORTED_WORKFLOWS:
        return False
    if sku_token and needs_products:
        return True
    if clean_workflow == "catalog":
        return bool(needs_products)
    if clean_workflow == "knowledge":
        return bool(needs_knowledge)
    return False


def _workflow_source(workflow: str) -> ComponentSource:
    if workflow == "knowledge":
        return ComponentSource.KNOWLEDGE
    if workflow == "general_talking":
        return ComponentSource.ERROR
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


def _fallback_workflow_decision(*, reason: str, confidence: float = 0.0) -> WorkflowDecision:
    return WorkflowDecision(
        workflow="fallback",
        source=ComponentSource.ERROR,
        needs_products=False,
        needs_knowledge=False,
        needs_clarification=True,
        store_overview_request=False,
        knowledge_query="",
        reason=reason,
        confidence=max(0.0, min(1.0, float(confidence))),
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
    """Legacy prompt-based route selector retained for regression coverage only."""
    from app.services.chat.routing.legacy_llm_routing import (
        decide_execution_mode_with_llm as legacy_decide_execution_mode_with_llm,
    )

    return await legacy_decide_execution_mode_with_llm(
        text=text,
        channel=channel,
        locale=locale,
        detail_has_filters=detail_has_filters,
        detail_request=detail_request,
        sku_tokens=sku_tokens,
        capabilities=capabilities,
    )
