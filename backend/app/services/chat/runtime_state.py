from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ExternalCallState:
    count: int = 0
    llm_count: int = 0
    retries_used: int = 0
    budget_exceeded_reason: str = ""
    slowest_call_ms: float = 0.0
    slowest_call_name: str = ""
    by_name: Dict[str, int] = field(default_factory=dict)

    def to_debug(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "external_call_count": int(self.count),
            "llm_call_count": int(self.llm_count),
            "external_call_retries_used": int(self.retries_used),
            "external_call_counts": dict(self.by_name or {}),
        }
        if self.budget_exceeded_reason:
            payload["external_call_budget_exceeded_reason"] = str(self.budget_exceeded_reason)
        return payload


@dataclass
class LatencySpans:
    values: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls) -> "LatencySpans":
        return cls(
            values={
                "total_ms": 0.0,
                "intent_routing_ms": 0.0,
                "detail_mode_triggered": False,
                "detail_query_parser_ms": 0.0,
                "retrieval_gate_ms": 0.0,
                "vector_search_ms": 0.0,
                "db_product_lookup_ms": 0.0,
                "projection_lookup_ms": 0.0,
                "tickets_service_ms": 0.0,
                "llm_calls_count": 0,
                "llm_parse_ms": 0.0,
                "llm_answer_ms": 0.0,
                "response_build_ms": 0.0,
            }
        )


@dataclass
class ChatExecutionContext:
    run_id: str
    channel: str
    conversation_id: int
    detail_mode_enabled: bool = False
    heuristic_currency: str = "USD"
    text: str = ""
    debug_meta: Dict[str, Any] = field(default_factory=dict)
    spans: Dict[str, Any] = field(default_factory=dict)
    external_state: ExternalCallState = field(default_factory=ExternalCallState)
    token_usage: Optional[Dict[str, Any]] = None
