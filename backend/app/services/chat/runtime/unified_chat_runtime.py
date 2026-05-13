from __future__ import annotations

import inspect
import time
from typing import Any, Dict, Optional

from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai.llm_service import llm_service
from app.services.chat.observability import runtime_metrics
import app.services.chat.runtime.alias_cache as alias_cache
import app.services.chat.parsing.parser_rule_cache as parser_rule_cache
import app.services.chat.routing.routing_policy as routing_policy
from app.services.chat.parsing.detail_query_parser import DetailQuery, DetailQueryParser
from app.services.chat.parsing.llm_attribute_extractor import infer_detail_query
from app.services.catalog.attributes_service import eav_service
from app.services.chat.routing.decision_engine import build_decision_state
from app.services.chat.routing.understanding import build_understanding_result
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.chat.runtime import conversation_state
from app.services.chat.runtime.search_plan import build_search_plan
from app.services.chat.runtime.agentic_adapter import (
    apply_agentic_fallback_debug,
    apply_agentic_success_debug,
    coerce_agentic_result,
)
from app.services.chat.agentic.orchestrator import AgentRunOutcome
from app.services.chat.runtime.execution_coordinator import (
    build_initial_debug_meta,
    finalize_agentic_response,
    finalize_component_response,
    finalize_runtime_error,
    safe_conversation_id,
)
from app.services.chat.runtime.fallback_policy import agentic_failure_reason


async def process_chat(self, req: ChatRequest, channel: Optional[str] = None) -> ChatResponse:
    total_started = time.perf_counter()
    spans = self._new_latency_spans()
    capabilities = build_chat_runtime_capabilities()

    run_id = f"chat-{int(time.time() * 1000)}"
    channel = channel or "widget"
    config_fingerprint = self._config_fingerprint()
    debug_meta: Dict[str, Any] = build_initial_debug_meta(
        channel=channel,
        config_fingerprint=config_fingerprint,
    )
    debug_meta["run_id"] = run_id
    llm_service.begin_token_tracking()

    text = req.message or ""
    detail_mode_enabled = False
    conversation_id_value: int = int(req.conversation_id or 0) if req.conversation_id else 0

    try:
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        conversation_id_value = safe_conversation_id(conversation, conversation_id_value)

        alias_map: Dict[str, Dict[str, str]] = {}
        parser_rules = parser_rule_cache.get_cached_parser_rules()
        if hasattr(self.db, "execute"):
            try:
                alias_map = await alias_cache.get_alias_map(self.db)
            except Exception as alias_exc:
                debug_meta["alias_cache_error"] = str(alias_exc)
            try:
                parser_rules = await parser_rule_cache.get_parser_rules(self.db)
            except Exception as parser_exc:
                debug_meta["parser_rule_cache_error"] = str(parser_exc)
        sku_tokens = routing_policy.extract_sku_tokens(text)
        existing_attribute_filters: Dict[str, str] = {}
        if capabilities.chat_conversation_state_enabled and conversation_id_value:
            try:
                loaded_state = await self.get_conversation_state(conversation_id_value)
                existing_attribute_filters = dict(
                    conversation_state.load_memory_state(loaded_state).last_attribute_filters or {}
                )
                if existing_attribute_filters:
                    debug_meta["conversation_existing_attribute_filters"] = dict(existing_attribute_filters)
            except Exception as state_exc:
                debug_meta["conversation_existing_attribute_filter_error"] = str(state_exc)
        searchable_attribute_names = []
        searchable_attribute_metadata = []
        if hasattr(self.db, "execute"):
            try:
                searchable_attribute_metadata = await eav_service.get_searchable_attribute_metadata(self.db)
                searchable_attribute_names = [
                    str(item.get("name") or "").strip()
                    for item in searchable_attribute_metadata
                    if str(item.get("name") or "").strip()
                ]
                debug_meta["catalog_searchable_attribute_names"] = list(searchable_attribute_names)
                debug_meta["catalog_searchable_attribute_metadata"] = list(searchable_attribute_metadata)
            except Exception as attr_exc:
                debug_meta["catalog_searchable_attribute_error"] = str(attr_exc)
        understanding = await build_understanding_result(
            user_text=text,
            locale=str(req.locale or ""),
            channel=channel,
            sku_tokens=sku_tokens,
        )
        debug_meta["understanding"] = dict(understanding.debug or {})
        debug_meta["understanding_workflow_hypothesis"] = understanding.workflow_hypothesis
        debug_meta["understanding_intent_confidence"] = understanding.intent_confidence
        debug_meta["understanding_reason"] = understanding.reason
        debug_meta["understanding_intent"] = understanding.intent
        debug_meta["understanding_subintent"] = understanding.subintent
        debug_meta["understanding_response_policy"] = understanding.response_policy
        debug_meta["understanding_user_goal"] = understanding.user_goal
        debug_meta["understanding_pending_task_type"] = understanding.pending_task_type
        debug_meta["understanding_missing_slot"] = understanding.missing_slot
        debug_meta["understanding_failure_reason"] = str(understanding.failure_reason or "")
        debug_meta["understanding_knowledge_query"] = understanding.knowledge_query
        debug_meta["understanding_llm_call_count"] = int(understanding.llm_call_count or 0)
        entity_hints = dict(understanding.entity_hints or {})
        has_product_signal = bool(entity_hints.get("has_product_signal"))
        has_product_detail_signal = bool(entity_hints.get("has_product_detail_signal"))
        should_extract_product_detail = bool(
            has_product_signal
            or understanding.needs_products
            or str(understanding.intent or "").strip().lower() == "product_information"
            or str(understanding.workflow_hypothesis or "").strip().lower() in {"catalog", "mixed"}
        )

        if should_extract_product_detail:
            detail_inference = await infer_detail_query(
                user_text=text,
                workflow="catalog",
                alias_map=alias_map,
                parser_rules=parser_rules,
                existing_filters=existing_attribute_filters,
                db=self.db,
                searchable_attribute_names=searchable_attribute_names,
                searchable_attribute_metadata=searchable_attribute_metadata,
            )
            detail = DetailQueryParser.build_from_inference(
                inference=detail_inference,
                parser_rules=parser_rules,
                searchable_attribute_names=searchable_attribute_names,
            )
            if has_product_detail_signal and not detail.is_detail_request:
                detail = DetailQuery(
                    requested_fields=list(detail.requested_fields or ["attributes"]),
                    attribute_filters=dict(detail.attribute_filters or {}),
                    wants_image=bool(detail.wants_image),
                    is_detail_request=True,
                    semantic_hints=list(detail.semantic_hints or []),
                    unknown_terms=list(getattr(detail, "unknown_terms", []) or []),
                    clarify_focus=str(detail.clarify_focus or "detail_request_needs_specific_product"),
                )
            detail_llm_calls = int(detail_inference.llm_call_count or 0)
            debug_meta.update(dict(detail_inference.debug or {}))
        else:
            detail = DetailQuery(
                requested_fields=[],
                attribute_filters={},
                wants_image=False,
                is_detail_request=False,
                semantic_hints=[],
                unknown_terms=[],
                clarify_focus="",
            )
            detail_llm_calls = 0

        decision_state = build_decision_state(
            understanding=understanding,
            user_text=text,
            channel=channel,
            capabilities=capabilities,
        )
        debug_meta["decision_state"] = {
            "internal_workflow": decision_state.internal_workflow,
            "public_workflow": decision_state.public_workflow,
            "intent_confidence": decision_state.intent_confidence,
            "retrieval_confidence": decision_state.retrieval_confidence,
            "answerability": decision_state.answerability,
            "reason": decision_state.reason,
            "failure_reason": decision_state.failure_reason,
            "intent": decision_state.intent,
            "subintent": decision_state.subintent,
            "response_policy": decision_state.response_policy,
            "user_goal": decision_state.user_goal,
        }
        execution_mode = "component"
        execution_decision = decision_state.execution_decision
        if execution_decision is None or decision_state.route_decision is None:
            raise RuntimeError("decision engine returned no route decision")
        route_decision = execution_decision.route_decision
        selection_source = execution_decision.selection_source
        execution_mode = execution_decision.execution_mode

        public_routing = route_decision.to_public_routing(
            execution_mode=execution_mode,
            selection_source=selection_source,
        )
        debug_meta["workflow"] = route_decision.workflow
        debug_meta["workflow_source"] = route_decision.source.value
        debug_meta["workflow_needs_products"] = route_decision.needs_products
        debug_meta["workflow_needs_knowledge"] = route_decision.needs_knowledge
        debug_meta["workflow_needs_clarification"] = route_decision.needs_clarification
        debug_meta["workflow_store_overview_request"] = route_decision.store_overview_request
        debug_meta["execution_mode"] = execution_mode
        debug_meta["routing_selection_source"] = selection_source
        debug_meta["routing"] = public_routing.model_dump(mode="json")
        debug_meta["routing_snapshot"] = runtime_metrics.routing_snapshot(
            route_decision=route_decision,
            execution_decision=execution_decision,
        )
        debug_meta["routing_confidence_gate_applied"] = execution_decision.confidence_gate_applied
        debug_meta["routing_timeout_retry_used"] = execution_decision.timeout_retry_used
        debug_meta["routing_failure_reason"] = str(decision_state.failure_reason or "")
        debug_meta["agentic"] = {
            "selected": execution_decision.execution_mode == "agentic",
            "selection_reason": execution_decision.reason,
            "selection_source": execution_decision.selection_source,
            "feature_enabled": execution_decision.feature_enabled,
            "channel_allowed": execution_decision.channel_allowed,
            "tool_suitable": execution_decision.tool_suitable,
            "llm_reason": execution_decision.llm_reason,
            "llm_confidence": execution_decision.llm_confidence,
            "llm_workflow": execution_decision.llm_workflow,
            "llm_execution_mode": execution_decision.llm_execution_mode,
            "confidence_gate_applied": execution_decision.confidence_gate_applied,
            "timeout_retry_used": execution_decision.timeout_retry_used,
            "used_tools": False,
            "trace": [],
            "fallback_to_component": False,
        }

        if execution_mode == "agentic" and execution_decision is not None:
            agentic_search_plan = build_search_plan(
                user_text=text,
                workflow=route_decision.workflow,
                detail=detail,
                sku_tokens=sku_tokens,
                knowledge_query=str(route_decision.knowledge_query or ""),
            )
            agentic_started = time.perf_counter()
            agentic_result = None
            agentic_error: Optional[Exception] = None
            try:
                agentic_kwargs = {
                    "user_text": text,
                    "conversation_id": conversation_id_value,
                    "run_id": run_id,
                    "channel": channel,
                    "reply_language": str(req.locale or "en-US"),
                }
                try:
                    signature = inspect.signature(self._run_agentic_workflow)
                    if "search_plan" in signature.parameters:
                        agentic_kwargs["search_plan"] = agentic_search_plan
                except Exception:
                    agentic_kwargs["search_plan"] = agentic_search_plan
                agentic_result = await self._run_agentic_workflow(**agentic_kwargs)
            except Exception as exc:
                agentic_error = exc
                debug_meta["agentic_error"] = str(exc)
                debug_meta["agentic_failure_reason"] = f"agentic_failed:{type(exc).__name__}"
            self._add_latency_span(
                spans,
                "agentic_orchestrator_ms",
                (time.perf_counter() - agentic_started) * 1000.0,
            )
            normalized_agentic_result = coerce_agentic_result(agentic_result)

            fallback_enabled = bool(capabilities.agentic_enable_fallback)
            if normalized_agentic_result.outcome == AgentRunOutcome.TOOL_SUCCESS:
                apply_agentic_success_debug(
                    debug_meta=debug_meta,
                    agentic_result=normalized_agentic_result,
                )
                return await finalize_agentic_response(
                    self,
                    conversation_id=conversation_id_value,
                    routing=public_routing,
                    query_summary=text,
                    agentic_result=normalized_agentic_result,
                    user_text=text,
                    channel=channel,
                    run_id=run_id,
                    debug_meta=debug_meta,
                    spans=spans,
                    total_started=total_started,
                )

            fallback_result = normalized_agentic_result
            if agentic_error is not None and not fallback_enabled:
                raise agentic_error
            if agentic_error is not None:
                fallback_result = coerce_agentic_result(agentic_result)
                fallback_result.fallback_reason = "agentic_error"
                debug_meta["agentic_failure_reason"] = agentic_failure_reason(
                    fallback_reason="agentic_error",
                    existing_failure_reason=str(debug_meta.get("agentic_failure_reason") or ""),
                )
            apply_agentic_fallback_debug(debug_meta=debug_meta, agentic_result=fallback_result)
            if normalized_agentic_result.outcome == AgentRunOutcome.EMPTY and not fallback_enabled:
                raise RuntimeError("agentic workflow returned no result")

        component_started = time.perf_counter()
        component_result = await self._run_component_pipeline(
            request=req,
            conversation_id=conversation_id_value,
            run_id=run_id,
            route_decision_override=route_decision,
            detail_override=detail,
            llm_call_count_override=int(understanding.llm_call_count or 0) + int(detail_llm_calls or 0),
            routing_selection_source=selection_source,
            internal_workflow_override=decision_state.internal_workflow,
            decision_state_override=decision_state,
            channel=channel,
        )
        self._add_latency_span(
            spans,
            "component_pipeline_ms",
            (time.perf_counter() - component_started) * 1000.0,
        )
        response, detail_mode_enabled = await finalize_component_response(
            self,
            component_result=component_result,
            conversation_id=conversation_id_value,
            user_text=text,
            channel=channel,
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
        )
        return response
    except Exception as exc:
        try:
            if hasattr(self.db, "rollback"):
                await self.db.rollback()
                debug_meta["component_pipeline_rollback"] = True
        except Exception as rollback_exc:
            debug_meta["component_pipeline_rollback"] = False
            debug_meta["component_pipeline_rollback_error"] = str(rollback_exc)

        debug_meta["component_mode"] = "error"
        debug_meta["component_pipeline_error"] = str(exc)
        return await finalize_runtime_error(
            self,
            error=exc,
            conversation_id=conversation_id_value,
            user_text=text,
            channel=channel,
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_enabled,
        )
