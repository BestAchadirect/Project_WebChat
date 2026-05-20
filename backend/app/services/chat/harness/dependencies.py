from __future__ import annotations

from app.services.catalog.attributes_service import eav_service
from app.services.chat.agentic.orchestrator import AgentRunOutcome
from app.services.chat.harness.context import ChatHarnessDependencies
from app.services.chat.observability import runtime_metrics
from app.services.chat.parsing.detail_query_parser import DetailQuery, DetailQueryParser
from app.services.chat.parsing.llm_attribute_extractor import (
    infer_detail_query,
    is_browse_like_product_request,
    should_demote_attribute_detail_to_browse,
)
from app.services.chat.routing.decision_engine import build_decision_state
from app.services.chat.routing.understanding import build_understanding_result
from app.services.chat.runtime import conversation_state
from app.services.chat.runtime.agentic_adapter import (
    apply_agentic_fallback_debug,
    apply_agentic_success_debug,
    coerce_agentic_result,
)
from app.services.chat.runtime.fallback_policy import agentic_failure_reason
from app.services.chat.runtime.search_plan import build_search_plan
from app.services.chat.harness.support import safe_conversation_id
import app.services.chat.parsing.parser_rule_cache as parser_rule_cache
import app.services.chat.routing.routing_policy as routing_policy
import app.services.chat.runtime.alias_cache as alias_cache


def build_default_harness_dependencies() -> ChatHarnessDependencies:
    return ChatHarnessDependencies(
        safe_conversation_id=safe_conversation_id,
        alias_cache=alias_cache,
        parser_rule_cache=parser_rule_cache,
        routing_policy=routing_policy,
        DetailQuery=DetailQuery,
        DetailQueryParser=DetailQueryParser,
        infer_detail_query=infer_detail_query,
        is_browse_like_product_request=is_browse_like_product_request,
        should_demote_attribute_detail_to_browse=should_demote_attribute_detail_to_browse,
        eav_service=eav_service,
        conversation_state=conversation_state,
        build_understanding_result=build_understanding_result,
        build_decision_state=build_decision_state,
        runtime_metrics=runtime_metrics,
        build_search_plan=build_search_plan,
        apply_agentic_fallback_debug=apply_agentic_fallback_debug,
        apply_agentic_success_debug=apply_agentic_success_debug,
        coerce_agentic_result=coerce_agentic_result,
        AgentRunOutcome=AgentRunOutcome,
        agentic_failure_reason=agentic_failure_reason,
    )
