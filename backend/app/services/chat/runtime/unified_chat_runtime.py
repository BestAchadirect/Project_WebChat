from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai.llm_service import llm_service
from app.services.chat.observability import runtime_metrics
import app.services.chat.runtime.alias_cache as alias_cache
import app.services.chat.parsing.parser_rule_cache as parser_rule_cache
import app.services.chat.routing.routing_policy as routing_policy
from app.services.chat.parsing.detail_query_parser import DetailQueryParser
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.chat.runtime.agentic_adapter import (
    apply_agentic_fallback_debug,
    apply_agentic_success_debug,
)
from app.services.chat.runtime.execution_coordinator import (
    build_initial_debug_meta,
    finalize_agentic_response,
    finalize_component_response,
    finalize_runtime_error,
    safe_conversation_id,
)


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
        detail = DetailQueryParser.parse(
            user_text=text,
            nlu_data={},
            alias_map=alias_map,
            parser_rules=parser_rules,
        )
        sku_tokens = routing_policy.extract_sku_tokens(text)
        execution_mode = "component"
        execution_decision = await routing_policy.decide_execution_mode_with_llm(
            text=text,
            channel=channel,
            locale=str(req.locale or ""),
            detail_has_filters=bool(detail.attribute_filters),
            detail_request=bool(detail.is_detail_request),
            sku_tokens=sku_tokens,
            capabilities=capabilities,
        )
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
            agentic_started = time.perf_counter()
            agentic_result = None
            agentic_error: Optional[Exception] = None
            try:
                agentic_result = await self._run_agentic_workflow(
                    user_text=text,
                    conversation_id=conversation_id_value,
                    run_id=run_id,
                    channel=channel,
                    reply_language=str(req.locale or "en-US"),
                )
            except Exception as exc:
                agentic_error = exc
                debug_meta["agentic_error"] = str(exc)
            self._add_latency_span(
                spans,
                "agentic_orchestrator_ms",
                (time.perf_counter() - agentic_started) * 1000.0,
            )

            fallback_enabled = bool(capabilities.agentic_enable_fallback)
            if agentic_result is not None and bool(getattr(agentic_result, "used_tools", False)):
                apply_agentic_success_debug(
                    debug_meta=debug_meta,
                    agentic_result=agentic_result,
                )
                return await finalize_agentic_response(
                    self,
                    conversation_id=conversation_id_value,
                    routing=public_routing,
                    query_summary=text,
                    agentic_result=agentic_result,
                    user_text=text,
                    channel=channel,
                    run_id=run_id,
                    debug_meta=debug_meta,
                    spans=spans,
                    total_started=total_started,
                )

            fallback_reason = "empty_result"
            if agentic_error is not None:
                fallback_reason = "agentic_error"
            elif agentic_result is not None and not bool(getattr(agentic_result, "used_tools", False)):
                fallback_reason = "no_tool_usage"
            apply_agentic_fallback_debug(debug_meta=debug_meta, fallback_reason=fallback_reason)
            if agentic_error is not None and not fallback_enabled:
                raise agentic_error
            if agentic_result is None and not fallback_enabled:
                raise RuntimeError("agentic workflow returned no result")

        component_started = time.perf_counter()
        component_result = await self._run_component_pipeline(
            request=req,
            conversation_id=conversation_id_value,
            run_id=run_id,
            route_decision_override=route_decision,
            routing_selection_source=selection_source,
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
