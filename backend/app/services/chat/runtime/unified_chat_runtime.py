from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.core.config import settings
from app.schemas.chat import ChatComponent, ChatComponentType, ChatRequest, ChatResponse, ChatResponseMeta, ChatRouting
from app.services.ai.llm_service import llm_service
import app.services.chat.runtime.alias_cache as alias_cache
import app.services.chat.parsing.parser_rule_cache as parser_rule_cache
import app.services.chat.routing.routing_policy as routing_policy
from app.services.chat.components.types import ComponentSource
from app.services.chat.parsing.detail_query_parser import DetailQueryParser


async def process_chat(self, req: ChatRequest, channel: Optional[str] = None) -> ChatResponse:
    total_started = time.perf_counter()
    spans = self._new_latency_spans()

    run_id = f"chat-{int(time.time() * 1000)}"
    channel = channel or "widget"
    config_fingerprint = self._config_fingerprint()
    debug_meta: Dict[str, Any] = {
        "run_id": run_id,
        "workflow_path": "component_primary",
        "channel": channel,
        "config_fingerprint": config_fingerprint,
        "openai_timeout_seconds": float(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 12.0)),
        "openai_max_retries": int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
        "component_mode": "primary",
        "component_channel_allowed": True,
    }
    llm_service.begin_token_tracking()

    text = req.message or ""
    detail_mode_enabled = False
    conversation_id_value: int = int(req.conversation_id or 0) if req.conversation_id else 0

    def _safe_conversation_id(conv: Any, fallback: int = 0) -> int:
        try:
            return int(getattr(conv, "id", 0) or 0)
        except Exception:
            return int(fallback or 0)

    def _apply_component_debug(component_result: Any) -> None:
        debug_meta.update(dict(getattr(component_result, "debug", {}) or {}))
        debug_meta["component_mode"] = "primary"
        debug_meta["component_plan"] = list(debug_meta.get("component_plan") or [])
        external_call_counts = dict(getattr(component_result, "external_call_counts", {}) or {})
        debug_meta["external_call_counts"] = external_call_counts
        debug_meta["external_call_count"] = int(sum(external_call_counts.values()))
        debug_meta["llm_call_count"] = int(getattr(component_result, "llm_calls", 0) or 0)

    def _build_agentic_response(
        *,
        routing: ChatRouting,
        query_summary: str,
        agentic_result: Any,
    ) -> ChatResponse:
        assistant_text = str(getattr(agentic_result, "final_reply", "") or "").strip()
        product_carousel = list(getattr(agentic_result, "product_carousel", []) or [])
        follow_up_questions = [
            str(item or "").strip()
            for item in list(getattr(agentic_result, "follow_up_questions", []) or [])
            if str(item or "").strip()
        ]
        components: list[ChatComponent] = []
        if assistant_text:
            components.append(
                ChatComponent(
                    type=ChatComponentType.ASSISTANT_MESSAGE,
                    data={"text": assistant_text},
                )
            )
        if product_carousel:
            cards = []
            for card in product_carousel:
                cards.append(
                    {
                        "product_id": str(getattr(card, "id", "") or ""),
                        "object_id": getattr(card, "object_id", None),
                        "sku": str(getattr(card, "sku", "") or ""),
                        "title": str(getattr(card, "name", "") or ""),
                        "description": getattr(card, "description", None),
                        "price": float(getattr(card, "price", 0.0) or 0.0),
                        "currency": str(getattr(card, "currency", "USD") or "USD"),
                        "in_stock": str(getattr(card, "stock_status", "") or "").strip().lower() == "in_stock",
                        "stock_qty": None,
                        "image_url": getattr(card, "image_url", None),
                        "material": str(dict(getattr(card, "attributes", {}) or {}).get("material") or "").strip(),
                        "gauge": str(dict(getattr(card, "attributes", {}) or {}).get("gauge") or "").strip(),
                        "attributes": dict(getattr(card, "attributes", {}) or {}),
                        "product_url": getattr(card, "product_url", None),
                    }
                )
            components.append(
                ChatComponent(
                    type=ChatComponentType.PRODUCT_CARDS,
                    data={"cards": cards},
                )
            )
        if follow_up_questions:
            components.append(
                ChatComponent(
                    type=ChatComponentType.QUICK_REPLIES,
                    data={"items": list(follow_up_questions)},
                )
            )
        return ChatResponse(
            conversation_id=conversation_id_value,
            reply_text=assistant_text,
            carousel_msg=str(getattr(agentic_result, "carousel_msg", "") or ""),
            product_carousel=product_carousel,
            routing=routing,
            sources=list(getattr(agentic_result, "sources", []) or []),
            debug={},
            components=components,
            meta=ChatResponseMeta(
                query_summary=str(query_summary or ""),
                latency_ms=0.0,
                source="tool",
                llm_calls=0,
                embedding_calls=0,
                product_result_count=len(product_carousel),
                product_display_count=len(product_carousel),
                product_has_more=False,
            ),
        )

    async def _finalize_component_response(component_result: Any) -> ChatResponse:
        nonlocal detail_mode_enabled
        detail_mode_enabled = bool(getattr(component_result, "detail_mode_triggered", False))
        for span_key, span_value in dict(getattr(component_result, "spans", {}) or {}).items():
            self._add_latency_span(spans, str(span_key), float(span_value or 0.0))
        _apply_component_debug(component_result)
        token_usage = llm_service.consume_token_usage()
        return await self._finalize_with_latency(
            conversation_id=conversation_id_value,
            user_text=text,
            response=component_result.response,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
            channel=channel,
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_enabled,
            conversation_state=getattr(component_result, "conversation_state", None),
        )

    async def _finalize_agentic_response(*, routing: ChatRouting, agentic_result: Any) -> ChatResponse:
        response = _build_agentic_response(
            routing=routing,
            query_summary=text,
            agentic_result=agentic_result,
        )
        token_usage = llm_service.consume_token_usage()
        return await self._finalize_with_latency(
            conversation_id=conversation_id_value,
            user_text=text,
            response=response,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
            channel=channel,
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=False,
        )

    try:
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        conversation_id_value = _safe_conversation_id(conversation, conversation_id_value)

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

            fallback_enabled = bool(getattr(settings, "AGENTIC_ENABLE_FALLBACK", True))
            if agentic_result is not None and bool(getattr(agentic_result, "used_tools", False)):
                debug_meta["workflow_path"] = "agentic_primary"
                debug_meta["component_mode"] = "agentic"
                debug_meta["component_plan"] = ["agentic_workflow"]
                debug_meta["component_source"] = "tool"
                debug_meta["external_call_counts"] = {}
                debug_meta["external_call_count"] = int(len(list(getattr(agentic_result, "trace", []) or [])))
                debug_meta["llm_call_count"] = 0
                debug_meta["agentic"] = {
                    **dict(debug_meta.get("agentic") or {}),
                    "used_tools": True,
                    "trace": list(getattr(agentic_result, "trace", []) or []),
                    "fallback_to_component": False,
                }
                return await _finalize_agentic_response(
                    routing=public_routing,
                    agentic_result=agentic_result,
                )

            fallback_reason = "empty_result"
            if agentic_error is not None:
                fallback_reason = "agentic_error"
            elif agentic_result is not None and not bool(getattr(agentic_result, "used_tools", False)):
                fallback_reason = "no_tool_usage"
            debug_meta["agentic"] = {
                **dict(debug_meta.get("agentic") or {}),
                "fallback_to_component": True,
                "fallback_reason": fallback_reason,
            }
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
        return await _finalize_component_response(component_result)
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

        token_usage = llm_service.consume_token_usage()
        self._log_latency_error(
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_enabled,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
            error=exc,
        )

        error_response = ChatResponse(
            conversation_id=conversation_id_value,
            reply_text="I could not process that request right now.",
            carousel_msg="",
            product_carousel=[],
            routing=ChatRouting(
                workflow="fallback",
                execution_mode="component",
                needs_clarification=True,
                reason="runtime_error",
                selection_source="llm_fallback",
            ),
            sources=[],
            debug={},
            components=[
                ChatComponent(
                    type="error",
                    data={"message": "I could not process that request right now."},
                )
            ],
            meta=ChatResponseMeta(
                query_summary=text,
                latency_ms=0.0,
                source="error",
                llm_calls=0,
                embedding_calls=0,
                product_result_count=0,
                product_display_count=0,
                product_has_more=False,
            ),
        )
        return await self._finalize_with_latency(
            conversation_id=conversation_id_value,
            user_text=text,
            response=error_response,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
            channel=channel,
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_enabled,
        )
