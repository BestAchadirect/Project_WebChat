from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.chat.harness.trace import HarnessTrace


@dataclass(frozen=True)
class ChatHarnessDependencies:
    safe_conversation_id: Any
    alias_cache: Any
    parser_rule_cache: Any
    routing_policy: Any
    DetailQuery: Any
    DetailQueryParser: Any
    infer_detail_query: Any
    is_browse_like_product_request: Any
    should_demote_attribute_detail_to_browse: Any
    eav_service: Any
    conversation_state: Any
    build_understanding_result: Any
    build_decision_state: Any
    runtime_metrics: Any
    build_search_plan: Any
    apply_agentic_fallback_debug: Any
    apply_agentic_success_debug: Any
    coerce_agentic_result: Any
    AgentRunOutcome: Any
    agentic_failure_reason: Any


@dataclass
class ChatHarnessContext:
    service: Any
    request: Any
    channel: str
    trace: HarnessTrace
    run_id: str
    user_text: str
    conversation_id_value: int
    total_started: float
    spans: dict[str, Any]
    capabilities: Any
    debug_meta: dict[str, Any]
    current_step: str = "prepare_context"
    step_started: float = 0.0
    detail_mode_enabled: bool = False
