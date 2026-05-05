from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.chat.routing import routing_policy
from app.services.chat.routing.workflow_taxonomy import (
    INTERNAL_WORKFLOWS,
    internal_workflow_values_prompt,
)

ANSWERABILITY_VALUES = {"full", "partial", "none"}
ASSISTANT_INTENTS = {
    "product_information",
    "knowledge_policy",
    "general_talking",
    "off_topic",
    "clarify",
}
RESPONSE_POLICIES = {
    "answer_from_retrieved_data",
    "answer_from_allowed_capabilities",
    "friendly_scoped_reply",
    "safe_redirect",
    "ask_clarifying_question",
}


def normalize_internal_workflow(value: Any) -> str:
    workflow = str(value or "").strip().lower()
    if workflow in INTERNAL_WORKFLOWS:
        return workflow
    return "clarify"


def normalize_answerability(value: Any) -> str:
    answerability = str(value or "").strip().lower()
    if answerability in ANSWERABILITY_VALUES:
        return answerability
    return "none"


def normalize_assistant_intent(value: Any) -> str:
    intent = str(value or "").strip().lower()
    if intent in ASSISTANT_INTENTS:
        return intent
    return "clarify"


def normalize_response_policy(value: Any) -> str:
    policy = str(value or "").strip().lower()
    if policy in RESPONSE_POLICIES:
        return policy
    return "ask_clarifying_question"


@dataclass(frozen=True)
class UnderstandingResult:
    normalized_text: str
    locale: str
    channel: str
    sku_tokens: List[str]
    workflow_hypothesis: str
    intent_confidence: float
    reason: str = ""
    knowledge_query: str = ""
    store_overview_request: bool = False
    needs_products: bool = False
    needs_knowledge: bool = False
    intent: str = "clarify"
    subintent: str = ""
    user_goal: str = ""
    product_query: str = ""
    response_policy: str = "ask_clarifying_question"
    clarify_question: str = ""
    pending_task_type: str = ""
    missing_slot: str = ""
    failure_reason: str = ""
    entity_hints: Dict[str, Any] = field(default_factory=dict)
    llm_call_count: int = 0
    debug: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workflow_hypothesis", normalize_internal_workflow(self.workflow_hypothesis))
        object.__setattr__(self, "intent", normalize_assistant_intent(self.intent))
        object.__setattr__(self, "response_policy", normalize_response_policy(self.response_policy))
        object.__setattr__(
            self,
            "intent_confidence",
            max(0.0, min(1.0, float(self.intent_confidence or 0.0))),
        )


@dataclass(frozen=True)
class DecisionState:
    internal_workflow: str
    public_workflow: str
    intent_confidence: float
    retrieval_confidence: float
    answerability: str
    reason: str = ""
    failure_reason: str = ""
    knowledge_query: str = ""
    store_overview_request: bool = False
    needs_products: bool = False
    needs_knowledge: bool = False
    intent: str = "clarify"
    subintent: str = ""
    user_goal: str = ""
    product_query: str = ""
    response_policy: str = "ask_clarifying_question"
    clarify_question: str = ""
    pending_task_type: str = ""
    missing_slot: str = ""
    entity_hints: Dict[str, Any] = field(default_factory=dict)
    route_decision: Optional[routing_policy.WorkflowDecision] = None
    execution_decision: Optional[routing_policy.ExecutionDecision] = None
    debug: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "internal_workflow", normalize_internal_workflow(self.internal_workflow))
        object.__setattr__(self, "answerability", normalize_answerability(self.answerability))
        object.__setattr__(self, "intent", normalize_assistant_intent(self.intent))
        object.__setattr__(self, "response_policy", normalize_response_policy(self.response_policy))
        object.__setattr__(
            self,
            "intent_confidence",
            max(0.0, min(1.0, float(self.intent_confidence or 0.0))),
        )
        object.__setattr__(
            self,
            "retrieval_confidence",
            max(0.0, min(1.0, float(self.retrieval_confidence or 0.0))),
        )


@dataclass(frozen=True)
class WorkflowResult:
    internal_workflow: str
    retrieval_source: str
    answerability: str
    retrieval_confidence: float = 0.0
    verification_reason: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    render_inputs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "internal_workflow", normalize_internal_workflow(self.internal_workflow))
        object.__setattr__(self, "answerability", normalize_answerability(self.answerability))
        object.__setattr__(
            self,
            "retrieval_confidence",
            max(0.0, min(1.0, float(self.retrieval_confidence or 0.0))),
        )
