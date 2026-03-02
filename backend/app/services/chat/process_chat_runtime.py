from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.chat import (
    ChatComponent,
    ChatContext,
    ChatRequest,
    ChatResponse,
    ChatResponseMeta,
    KnowledgeSource,
    ProductCard,
)
from app.services.ai.llm_service import llm_service
from app.services.currency_service import currency_service
from app.services.semantic_cache_service import semantic_cache_service
from app.services.chat.detail_query_parser import DetailQueryParser
from app.services.chat.detail_response_builder import DetailResponseBuilder
from app.services.chat.intent_router import IntentRouter
from app.services.chat.product_context import ProductContextAssembler
from app.services.chat.product_detail_resolver import ProductDetailResolver
from app.services.chat.response_consistency import ResponseConsistencyPolicy
from app.services.chat.retrieval_gate import RetrievalGate

logger = get_logger(__name__)


class EmbeddingSkippedReason(str, Enum):
    NOT_NEEDED = "not_needed"
    STRUCTURED_RESULTS_FOUND = "structured_results_found"
    BUDGET_EXCEEDED = "budget_exceeded"
    DISABLED_BY_ROUTE = "disabled_by_route"


class ExternalBudgetExceededReason(str, Enum):
    EXTERNAL_CALL_BUDGET = "external_call_budget"
    EXTERNAL_TIMEOUT = "external_timeout"
    EXTERNAL_CONNECTIVITY = "external_connectivity"
    LLM_CALL_CAP = "llm_call_cap"


async def process_chat(self, req: ChatRequest, channel: Optional[str] = None) -> ChatResponse:
    total_started = time.perf_counter()
    spans = self._new_latency_spans()

    run_id = f"chat-{int(time.time() * 1000)}"
    channel = channel or "widget"
    default_display_currency = (
        getattr(settings, "PRICE_DISPLAY_CURRENCY", None)
        or getattr(settings, "BASE_CURRENCY", None)
        or "USD"
    )
    heuristic_currency = (
        currency_service.extract_requested_currency(req.message or "") or str(default_display_currency).upper()
    )
    config_fingerprint = self._config_fingerprint()
    debug_meta: Dict[str, Any] = {
        "run_id": run_id,
        "route": "rag_strict",
        "channel": channel,
        "config_fingerprint": config_fingerprint,
        "openai_timeout_seconds": float(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 12.0)),
        "openai_max_retries": int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
        "llm_calls_enforced": max(0, int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0))) > 0,
        "sku_precheck_bypassed": False,
        "sku_precheck_bypass_reason": "",
        "component_channel_allowed": False,
        "image_only_filter_applied": False,
        "image_only_result_count": 0,
    }
    llm_service.begin_token_tracking()

    text = req.message or ""
    detail_mode_enabled = False
    external_state: Dict[str, Any] = {
        "count": 0,
        "llm_count": 0,
        "retries_used": 0,
        "budget_exceeded_reason": "",
        "slowest_call_ms": 0.0,
        "slowest_call_name": "",
        "by_name": {},
    }
    conversation_id_value: int = int(req.conversation_id or 0) if req.conversation_id else 0

    def _safe_conversation_id(conv: Any, fallback: int = 0) -> int:
        try:
            return int(getattr(conv, "id", 0) or 0)
        except Exception:
            return int(fallback or 0)

    def _apply_external_debug() -> None:
        debug_meta["external_call_count"] = int(external_state.get("count", 0))
        debug_meta["llm_call_count"] = int(external_state.get("llm_count", 0))
        debug_meta["external_call_retries_used"] = int(external_state.get("retries_used", 0))
        debug_meta["external_call_counts"] = dict(external_state.get("by_name", {}))
        if external_state.get("budget_exceeded_reason"):
            debug_meta["external_call_budget_exceeded_reason"] = str(external_state["budget_exceeded_reason"])

    async def _finalize_and_cache(response: ChatResponse, token_usage: Optional[Dict[str, Any]]) -> ChatResponse:
        _apply_external_debug()
        finalized = await self._finalize_with_latency(
            conversation_id=conversation_id_value,
            user_text=text,
            response=response,
            token_usage=token_usage,
            channel=channel,
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_enabled,
        )
        self._log_cache_stats_if_needed(run_id=run_id, debug_meta=debug_meta)
        return finalized

    try:
        # 1) Minimal validation only
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        conversation_id_value = _safe_conversation_id(conversation, conversation_id_value)

        # 2) Always process fresh request path.

        component_enabled = bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False))
        component_shadow_mode = bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False))
        component_require = bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False))
        component_channel_allowed = self._is_component_channel_allowed(channel=channel)
        component_enabled_for_channel = component_enabled and component_channel_allowed
        debug_meta["component_channel_allowed"] = bool(component_channel_allowed)

        if component_enabled and not component_channel_allowed:
            debug_meta["component_mode"] = "disabled_for_channel"

        if component_enabled_for_channel and not component_shadow_mode:
            component_started = time.perf_counter()
            try:
                component_result = await self._run_component_pipeline(
                    request=req,
                    conversation_id=conversation_id_value,
                    run_id=run_id,
                )
                detail_mode_enabled = bool(component_result.detail_mode_triggered)
                for span_key, span_value in dict(component_result.spans or {}).items():
                    self._add_latency_span(spans, str(span_key), float(span_value or 0.0))
                self._add_latency_span(
                    spans,
                    "response_build_ms",
                    (time.perf_counter() - component_started) * 1000.0,
                )
                debug_meta.update(dict(component_result.debug or {}))
                debug_meta["component_mode"] = "active"
                debug_meta["component_plan"] = list(
                    dict(component_result.debug or {}).get("component_plan") or []
                )
                external_state["llm_count"] = int(component_result.llm_calls or 0)
                external_state["by_name"] = dict(component_result.external_call_counts or {})
                external_state["count"] = int(sum(external_state["by_name"].values()))
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(
                    component_result.response,
                    token_usage if isinstance(token_usage, dict) else None,
                )
            except Exception as exc:
                debug_meta["component_mode"] = "error"
                debug_meta["component_pipeline_error"] = str(exc)
                recovery_conversation_id: Optional[int] = conversation_id_value or None
                try:
                    if hasattr(self.db, "rollback"):
                        await self.db.rollback()
                        debug_meta["component_pipeline_rollback"] = True
                        try:
                            user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
                            conversation = await self.get_or_create_conversation(
                                user,
                                recovery_conversation_id or req.conversation_id,
                            )
                            conversation_id_value = _safe_conversation_id(
                                conversation,
                                recovery_conversation_id or conversation_id_value,
                            )
                            debug_meta["component_pipeline_context_recovered"] = True
                        except Exception as recover_exc:
                            debug_meta["component_pipeline_context_recovered"] = False
                            debug_meta["component_pipeline_context_recover_error"] = str(recover_exc)
                except Exception as rollback_exc:
                    debug_meta["component_pipeline_rollback"] = False
                    debug_meta["component_pipeline_rollback_error"] = str(rollback_exc)
                if component_require:
                    self._add_latency_span(
                        spans,
                        "response_build_ms",
                        (time.perf_counter() - component_started) * 1000.0,
                    )
                    error_response = ChatResponse(
                        conversation_id=conversation_id_value,
                        reply_text="I could not process that request right now.",
                        carousel_msg="",
                        product_carousel=[],
                        follow_up_questions=[],
                        intent="fallback_general",
                        sources=[],
                        debug=debug_meta,
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
                        ),
                    )
                    token_usage = llm_service.consume_token_usage()
                    return await _finalize_and_cache(
                        error_response,
                        token_usage if isinstance(token_usage, dict) else None,
                    )
        elif component_enabled_for_channel and component_shadow_mode:
            debug_meta["component_mode"] = "shadow"
            shadow_started = time.perf_counter()
            try:
                shadow_result = await self._run_component_pipeline(
                    request=req,
                    conversation_id=conversation_id_value,
                    run_id=run_id,
                )
                debug_meta["component_shadow_component_plan"] = list(
                    dict(shadow_result.debug or {}).get("component_plan") or []
                )
                debug_meta["component_shadow_component_count"] = int(
                    len(list(shadow_result.response.components or []))
                )
                debug_meta["component_shadow_source"] = str(
                    dict(shadow_result.debug or {}).get("component_source") or ""
                )
            except Exception as exc:
                debug_meta["component_shadow_error"] = str(exc)
                recovery_conversation_id: Optional[int] = conversation_id_value or None
                try:
                    if hasattr(self.db, "rollback"):
                        await self.db.rollback()
                        debug_meta["component_shadow_rollback"] = True
                        try:
                            user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
                            conversation = await self.get_or_create_conversation(
                                user,
                                recovery_conversation_id or req.conversation_id,
                            )
                            conversation_id_value = _safe_conversation_id(
                                conversation,
                                recovery_conversation_id or conversation_id_value,
                            )
                            debug_meta["component_shadow_context_recovered"] = True
                        except Exception as recover_exc:
                            debug_meta["component_shadow_context_recovered"] = False
                            debug_meta["component_shadow_context_recover_error"] = str(recover_exc)
                except Exception as rollback_exc:
                    debug_meta["component_shadow_rollback"] = False
                    debug_meta["component_shadow_rollback_error"] = str(rollback_exc)
            finally:
                self._add_latency_span(
                    spans,
                    "component_shadow_ms",
                    (time.perf_counter() - shadow_started) * 1000.0,
                )

        # 3) Ultra-cheap SKU pre-check before NLU (single-SKU lookups only)
        debug_meta["sku_precheck_hit"] = False
        should_precheck, precheck_bypass_reason, precheck_candidates = self._should_run_sku_precheck(
            user_text=text,
            channel=channel,
        )
        if not should_precheck:
            debug_meta["sku_precheck_bypassed"] = True
            debug_meta["sku_precheck_bypass_reason"] = str(precheck_bypass_reason or "policy")
        else:
            sku_precheck_started = time.perf_counter()
            sku_candidate, sku_cards = await self._cheap_sku_precheck(
                user_text=text,
                limit=3,
                candidates=precheck_candidates,
            )
            self._add_latency_span(
                spans,
                "db_product_lookup_ms",
                (time.perf_counter() - sku_precheck_started) * 1000.0,
            )
            if sku_cards:
                debug_meta["sku_precheck_hit"] = True
                debug_meta["sku_precheck_code"] = sku_candidate
                response_build_started = time.perf_counter()
                quick_reply = (
                    f"I found {len(sku_cards)} product(s) matching code {sku_candidate}. "
                    "Showing the latest item details."
                )
                response = await self._response_renderer.render(
                    conversation_id=conversation_id_value,
                    route="search_specific",
                    reply_data={"reply": quick_reply, "carousel_hint": "", "recommended_questions": []},
                    product_carousel=list(sku_cards),
                    follow_up_questions=["Ask for price/stock/image for a specific SKU."],
                    sources=[],
                    debug=debug_meta,
                    reply_language=str(req.locale or "en-US"),
                    target_currency=str(heuristic_currency),
                    user_text=text,
                    apply_polish=False,
                )
                self._add_latency_span(
                    spans,
                    "response_build_ms",
                    (time.perf_counter() - response_build_started) * 1000.0,
                )
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)

        # 4) Load history after SKU pre-check
        history = []
        if conversation_id_value:
            history = await self.get_history(conversation_id_value, limit=8)
        max_history_tokens = max(64, int(getattr(settings, "CHAT_MAX_HISTORY_TOKENS", 1200)))
        history_for_llm = self._trim_history_for_llm(history, max_tokens=max_history_tokens)
        debug_meta["history_loaded_count"] = len(history)
        debug_meta["history_for_llm_count"] = len(history_for_llm)
        debug_meta["history_token_cap"] = max_history_tokens

        # 5) Heuristic-first NLU with threshold
        llm_parse_started = time.perf_counter()
        try:
            nlu_data = await self._run_nlu(
                user_text=text,
                history=history_for_llm,
                locale=req.locale,
                run_id=run_id,
                external_state=external_state,
                debug_meta=debug_meta,
            )
        except Exception:
            route_kind = "vague" if self._looks_vague_query(text) else "knowledge_query"
            response = await self._build_route_fallback_response(
                conversation_id=conversation_id_value,
                route_kind=route_kind,
                reason=str(external_state.get("budget_exceeded_reason") or ExternalBudgetExceededReason.EXTERNAL_CONNECTIVITY.value),
                user_text=text,
                reply_language=str(req.locale or "en-US"),
                target_currency=str(heuristic_currency),
                debug_meta=debug_meta,
            )
            self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - llm_parse_started) * 1000.0)
            token_usage = llm_service.consume_token_usage()
            return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)

        self._add_latency_span(spans, "llm_parse_ms", (time.perf_counter() - llm_parse_started) * 1000.0)
        debug_meta["nlu"] = nlu_data

        reply_language = await self._resolve_reply_language(
            nlu_data=nlu_data,
            user_text=text,
            locale=req.locale,
            run_id=run_id,
        )
        debug_meta["reply_language"] = reply_language
        target_currency = await self._resolve_target_currency(nlu_data=nlu_data, user_text=text)
        debug_meta["target_currency"] = target_currency

        # 6) Intent routing + retrieval gate
        intent_started = time.perf_counter()
        intent_decision = IntentRouter.resolve(
            nlu_data=nlu_data,
            user_text=text,
            clean_code_candidate=self._clean_code_candidate,
            extract_sku=self._extract_sku,
            looks_like_code=self._looks_like_code,
        )
        self._add_latency_span(spans, "intent_routing_ms", (time.perf_counter() - intent_started) * 1000.0)
        search_query = intent_decision.search_query
        intent = intent_decision.intent
        show_products_flag = intent_decision.show_products_flag
        nlu_product_code = intent_decision.nlu_product_code
        sku_token = intent_decision.sku_token

        detail_parser_started = time.perf_counter()
        detail_request = DetailQueryParser.parse(user_text=text, nlu_data=nlu_data)
        self._add_latency_span(spans, "detail_query_parser_ms", (time.perf_counter() - detail_parser_started) * 1000.0)

        detail_mode_enabled = bool(getattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", True)) and bool(
            detail_request.is_detail_request
        )
        debug_meta["detail_mode_enabled"] = detail_mode_enabled
        debug_meta["requested_fields"] = list(detail_request.requested_fields)
        debug_meta["attribute_filters"] = dict(detail_request.attribute_filters)
        nlu_fields = [str(item).strip().lower() for item in list(nlu_data.get("requested_fields", []) or [])]
        if sorted(set(nlu_fields)) != sorted(set(detail_request.requested_fields)):
            logger.warning(
                "detail parser adjusted requested_fields from nlu",
                extra={
                    "event": "detail_parser_nlu_mismatch",
                    "nlu_fields": sorted(set(nlu_fields)),
                    "parser_fields": sorted(set(detail_request.requested_fields)),
                },
            )

        gate_started = time.perf_counter()
        retrieval_decision = RetrievalGate.decide(
            intent=intent,
            show_products_flag=show_products_flag,
            is_product_intent=intent_decision.is_product_intent,
            sku_token=sku_token,
            strict_separation=bool(getattr(settings, "CHAT_STRICT_RETRIEVAL_SEPARATION_ENABLED", False)),
            has_attribute_filters=bool(detail_request.attribute_filters),
            detail_request=bool(detail_request.is_detail_request),
            user_text=text,
            infer_jewelry_type_filter=self._infer_jewelry_type_filter,
            is_question_like_fn=self._is_question_like,
            is_complex_query_fn=self._is_complex_query,
            count_policy_topics_fn=self._count_policy_topics,
        )
        self._add_latency_span(spans, "retrieval_gate_ms", (time.perf_counter() - gate_started) * 1000.0)

        use_products = retrieval_decision.use_products
        use_knowledge = retrieval_decision.use_knowledge
        is_question_like = retrieval_decision.is_question_like
        is_complex = retrieval_decision.is_complex
        policy_topic_count = retrieval_decision.policy_topic_count
        is_policy_intent = retrieval_decision.is_policy_intent
        looks_like_product = retrieval_decision.looks_like_product
        ctx = ChatContext(
            text=text,
            is_question_like=is_question_like,
            looks_like_product=looks_like_product,
            has_store_intent=use_products,
            is_policy_intent=is_policy_intent,
            policy_topic_count=policy_topic_count,
            sku_token=sku_token,
            requested_currency=target_currency if target_currency != default_display_currency.upper() else None,
        )

        debug_meta["intent"] = intent
        debug_meta["path_kind"] = (
            "product_only"
            if use_products and not use_knowledge
            else "knowledge_only"
            if use_knowledge and not use_products
            else "mixed"
            if use_products and use_knowledge
            else "none"
        )
        debug_meta["retrieval_gate"] = {
            "use_products": use_products,
            "use_knowledge": use_knowledge,
            "is_complex": is_complex,
            "is_policy_intent": is_policy_intent,
            "policy_topic_count": policy_topic_count,
        }

        # Optional agentic read-only tool path for live-state/tool-needed requests.
        agent_result = None
        agentic_enabled = self._is_agentic_channel_enabled(channel) and max(
            0, int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0))
        ) == 0
        agentic_suitable = self._is_agentic_tool_suitable(
            user_text=text,
            intent=intent,
            sku_token=sku_token,
        )
        if agentic_enabled and agentic_suitable:
            debug_meta["agentic"] = {
                "attempted": True,
                "eligible": True,
                "channel": channel,
            }
            try:
                orchestrator = self._new_agent_orchestrator(
                    run_id=run_id,
                    channel=channel,
                )
                agent_result = await orchestrator.run(
                    user_text=text,
                    history=history_for_llm,
                    reply_language=reply_language,
                )
            except Exception as exc:
                logger.error(f"Agentic orchestration failed: {exc}")
                debug_meta["agentic_error"] = str(exc)
                agent_result = None

            if agent_result and agent_result.final_reply and agent_result.used_tools:
                debug_meta["agentic"] = {
                    "attempted": True,
                    "eligible": True,
                    "used_tools": True,
                    "tool_call_count": len(agent_result.trace),
                    "channel": channel,
                }
                agent_reply_data = await self._ensure_reply_consistency_with_products(
                    reply_data={
                        "reply": agent_result.final_reply,
                        "carousel_hint": agent_result.carousel_msg or "",
                        "recommended_questions": list(agent_result.follow_up_questions or []),
                    },
                    has_products=bool(agent_result.product_carousel),
                    reply_language=reply_language,
                    run_id=run_id,
                )
                response_build_started = time.perf_counter()
                response = await self._response_renderer.render(
                    conversation_id=conversation_id_value,
                    route="agentic_tools",
                    reply_data=agent_reply_data,
                    product_carousel=list(agent_result.product_carousel or []),
                    follow_up_questions=list(agent_result.follow_up_questions or []),
                    sources=list(agent_result.sources or []),
                    debug=debug_meta,
                    reply_language=reply_language,
                    target_currency=target_currency,
                    user_text=text,
                    apply_polish=False,
                )
                self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
                token_usage = llm_service.consume_token_usage() or {}
                if isinstance(token_usage, dict):
                    token_usage["agent_tool_trace"] = list(agent_result.trace or [])
                    token_usage["agent_used_tools"] = True
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)

            fallback_enabled = bool(getattr(settings, "AGENTIC_ENABLE_FALLBACK", True))
            if not fallback_enabled:
                debug_meta["agentic"] = {
                    "attempted": True,
                    "eligible": True,
                    "used_tools": bool(agent_result and agent_result.used_tools),
                    "fallback": False,
                    "channel": channel,
                }
                fallback_text = await self._localize_ui_text(
                    reply_language=reply_language,
                    text="I could not complete that request right now. Please try again.",
                    run_id=run_id,
                )
                response_build_started = time.perf_counter()
                response = await self._response_renderer.render(
                    conversation_id=conversation_id_value,
                    route="agentic_tools",
                    reply_data={"reply": fallback_text, "carousel_hint": "", "recommended_questions": []},
                    product_carousel=[],
                    follow_up_questions=[],
                    sources=[],
                    debug=debug_meta,
                    reply_language=reply_language,
                    target_currency=target_currency,
                    user_text=text,
                    apply_polish=False,
                )
                self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
        else:
            debug_meta["agentic"] = {
                "attempted": False,
                "eligible": bool(agentic_suitable),
                "enabled": bool(agentic_enabled),
                "channel": channel,
            }

        # 7) SQL-first structured product retrieval
        query_embedding: Optional[List[float]] = None
        embedding_failed = False
        embedding_error: Optional[Exception] = None
        structured_results_found = False
        structured_meta: Dict[str, Any] = {}
        product_cards: List[ProductCard] = []
        best_distance: Optional[float] = None
        distance_by_id: Dict[str, float] = {}

        if (
            use_products
            and bool(getattr(settings, "CHAT_SQL_FIRST_ENABLED", True))
            and hasattr(self.db, "execute")
        ):
            structured_started = time.perf_counter()
            structured_result, structured_meta = await self._catalog_search.structured_search(
                sku_token=sku_token or nlu_product_code,
                attribute_filters=detail_request.attribute_filters,
                limit=20 if detail_mode_enabled else 10,
                candidate_cap=int(getattr(settings, "CHAT_STRUCTURED_CANDIDATE_CAP", 300)),
                catalog_version=str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
            )
            self._add_latency_span(spans, "db_product_lookup_ms", (time.perf_counter() - structured_started) * 1000.0)
            product_cards = list(structured_result.cards or [])
            best_distance = structured_result.best_distance
            distance_by_id = dict(structured_result.distance_by_id or {})
            structured_results_found = bool(product_cards)
            debug_meta["structured_sql_hit"] = structured_results_found
            debug_meta["structured_query_cache_hit"] = bool(structured_meta.get("structured_query_cache_hit", False))
            debug_meta["structured_candidate_cap"] = int(structured_meta.get("structured_candidate_cap", 0))
            debug_meta["projection_hit"] = bool(structured_meta.get("projection_hit", False))
            debug_meta["projection_lookup_ms"] = float(structured_meta.get("projection_lookup_ms", 0.0) or 0.0)
            debug_meta["structured_read_mode"] = str(structured_meta.get("structured_read_mode", "eav"))
            self._add_latency_span(spans, "projection_lookup_ms", float(structured_meta.get("projection_lookup_ms", 0.0) or 0.0))
        else:
            debug_meta["structured_sql_hit"] = False
            debug_meta["structured_query_cache_hit"] = False
            debug_meta["projection_hit"] = False
            debug_meta["projection_lookup_ms"] = 0.0
            debug_meta["structured_read_mode"] = "disabled"

        # 8) Embedding gating + fail-fast external call wrapper
        should_embed = False
        embedding_skip_reason = EmbeddingSkippedReason.NOT_NEEDED
        if use_knowledge:
            should_embed = True
        elif use_products:
            if structured_results_found:
                should_embed = False
                embedding_skip_reason = EmbeddingSkippedReason.STRUCTURED_RESULTS_FOUND
            else:
                should_embed = True

        if use_products and not use_knowledge and self._looks_vague_query(search_query):
            should_embed = True
            embedding_skip_reason = EmbeddingSkippedReason.NOT_NEEDED

        if not use_products and not use_knowledge:
            should_embed = False
            embedding_skip_reason = EmbeddingSkippedReason.DISABLED_BY_ROUTE

        if should_embed:
            embedding_started = time.perf_counter()
            try:
                query_embedding = await self._run_external_call(
                    external_state=external_state,
                    call_name="embedding_query",
                    call_factory=lambda: llm_service.generate_embedding(search_query),
                    run_id=run_id,
                    debug_meta=debug_meta,
                )
            except Exception as exc:
                embedding_failed = True
                embedding_error = exc
                debug_meta["embedding_error"] = str(exc)
                debug_meta["embedding_error_type"] = type(exc).__name__
                self._log_event(
                    run_id=run_id,
                    location="chat_service.embedding.error",
                    data={
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "use_products": bool(use_products),
                        "use_knowledge": bool(use_knowledge),
                    },
                )
            finally:
                self._add_latency_span(spans, "vector_search_ms", (time.perf_counter() - embedding_started) * 1000.0)
        else:
            debug_meta["embedding_skipped_reason"] = str(embedding_skip_reason.value)

        if embedding_failed:
            if bool(getattr(settings, "CHAT_FAIL_FAST_ON_EMBEDDING_ERROR", True)):
                debug_meta["embedding_fail_fast"] = True
                response_build_started = time.perf_counter()
                budget_reason = str(external_state.get("budget_exceeded_reason") or "").strip()
                if budget_reason:
                    route_kind = "detail_mode" if detail_mode_enabled else (
                        "knowledge_query" if use_knowledge else "browse_products"
                    )
                    response = await self._build_route_fallback_response(
                        conversation_id=conversation_id_value,
                        route_kind=route_kind,
                        reason=budget_reason,
                        user_text=text,
                        reply_language=reply_language,
                        target_currency=target_currency,
                        debug_meta=debug_meta,
                        product_carousel=list(product_cards[:3]) if product_cards else [],
                    )
                else:
                    response = await self._build_embedding_fail_fast_response(
                        conversation_id=conversation_id_value,
                        user_text=text,
                        reply_language=reply_language,
                        target_currency=target_currency,
                        debug_meta=debug_meta,
                        use_products=bool(use_products),
                        use_knowledge=bool(use_knowledge),
                    )
                self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
            raise embedding_error or RuntimeError("Embedding generation failed")

        allow_detail_cache = bool(getattr(settings, "CHAT_DETAIL_ENABLE_SEMANTIC_CACHE", False))
        # Product-only browse responses are deterministic and should not be served
        # from semantic response cache to avoid stale/free-form reply text.
        # Detail mode stays opt-in via CHAT_DETAIL_ENABLE_SEMANTIC_CACHE.
        allow_semantic_cache = (
            (not bool(detail_mode_enabled) and bool(use_knowledge))
            or (bool(detail_mode_enabled) and allow_detail_cache)
        )
        debug_meta["semantic_cache_hit"] = False
        if query_embedding is not None and allow_semantic_cache:
            cache_hit = await semantic_cache_service.get_hit(
                self.db,
                query_embedding=query_embedding,
                reply_language=reply_language,
                target_currency=target_currency,
            )
            if cache_hit:
                debug_meta["semantic_cache_hit"] = True
                debug_meta["semantic_cache_distance"] = cache_hit.distance
                cached = cache_hit.entry.response_json or {}
                cached_products = [ProductCard(**p) for p in cached.get("product_carousel", [])]
                cached_reply_text = str(cached.get("reply_text", ""))
                cached_carousel_msg = str(cached.get("carousel_msg", ""))
                cached_reply_text, cached_carousel_msg = await ResponseConsistencyPolicy.normalize_cached_response(
                    reply_text=cached_reply_text,
                    carousel_msg=cached_carousel_msg,
                    has_products=bool(cached_products),
                    localize_text=lambda text: self._localize_ui_text(
                        reply_language=reply_language,
                        text=text,
                        run_id=run_id,
                    ),
                )
                response = ChatResponse(
                    conversation_id=conversation_id_value,
                    reply_text=cached_reply_text,
                    carousel_msg=cached_carousel_msg,
                    product_carousel=cached_products,
                    follow_up_questions=list(cached.get("follow_up_questions", []) or []),
                    intent=str(cached.get("intent", "rag_strict")),
                    sources=[KnowledgeSource(**s) for s in cached.get("sources", [])],
                    debug=debug_meta,
                    view_button_text=str(cached.get("view_button_text", "View Product Details")),
                    material_label=str(cached.get("material_label", "Material")),
                    jewelry_type_label=str(cached.get("jewelry_type_label", "Jewelry Type")),
                )
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
        elif query_embedding is not None:
            if not allow_semantic_cache and use_products and not use_knowledge and not detail_mode_enabled:
                debug_meta["semantic_cache_skipped"] = "product_only_deterministic"
            else:
                debug_meta["semantic_cache_skipped"] = "detail_mode"

        # Vector product fallback only when needed
        if (
            use_products
            and query_embedding is not None
            and not structured_results_found
            and hasattr(self.db, "execute")
        ):
            product_search_limit = max(1, int(getattr(settings, "CHAT_VECTOR_TOP_K", 12)))
            product_search_started = time.perf_counter()
            vector_cards, _distances, best_distance, distance_by_id = await self.smart_product_search(
                query=search_query,
                query_embedding=query_embedding,
                limit=product_search_limit,
                run_id=run_id,
                extracted_code=nlu_product_code,
            )
            product_search_elapsed = (time.perf_counter() - product_search_started) * 1000.0
            prev_vector_ms = float(spans.get("vector_search_ms", 0.0) or 0.0)
            self._merge_catalog_metrics_into_spans(spans)
            if float(spans.get("vector_search_ms", 0.0) or 0.0) <= prev_vector_ms:
                self._add_latency_span(spans, "vector_search_ms", product_search_elapsed)
            product_cards = list(vector_cards)

        if detail_mode_enabled:
            resolver = ProductDetailResolver()
            resolution = resolver.resolve_detail_request(
                candidate_cards=product_cards,
                distance_by_id=distance_by_id,
                requested_fields=detail_request.requested_fields,
                attribute_filters=detail_request.attribute_filters,
                sku_token=sku_token,
                nlu_product_code=nlu_product_code,
                max_matches=int(getattr(settings, "CHAT_DETAIL_MAX_MATCHES", 3)),
                min_confidence=float(getattr(settings, "CHAT_DETAIL_MIN_CONFIDENCE", 0.55)),
            )
            detail_builder = DetailResponseBuilder()
            detail_payload = detail_builder.build_detail_reply(
                matches=resolution.matches,
                requested_fields=resolution.requested_fields,
                attribute_filters=resolution.attribute_filters,
                missing_fields_by_product=resolution.missing_fields_by_product,
                wants_image=detail_request.wants_image,
                max_matches=int(getattr(settings, "CHAT_DETAIL_MAX_MATCHES", 3)),
            )
            debug_meta["detail_match_count"] = len(resolution.matches)
            debug_meta["detail_card_policy_reason"] = detail_payload.card_policy_reason
            debug_meta["detail_has_exact_match"] = resolution.has_exact_match

            response_build_started = time.perf_counter()
            response = await self._response_renderer.render(
                conversation_id=conversation_id_value,
                route="detail_mode",
                reply_data={
                    "reply": detail_payload.reply_text,
                    "carousel_hint": detail_payload.carousel_msg,
                    "recommended_questions": list(detail_payload.follow_up_questions),
                },
                product_carousel=list(detail_payload.product_carousel),
                follow_up_questions=list(detail_payload.follow_up_questions),
                sources=[],
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=text,
                apply_polish=False,
            )
            self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
            token_usage = llm_service.consume_token_usage()
            return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)

        max_sub_questions = int(getattr(settings, "RAG_DECOMPOSE_MAX_SUBQUESTIONS", 5))
        kb_sources: List[KnowledgeSource] = []
        if use_knowledge and query_embedding is not None:
            kb_fetch_started = time.perf_counter()
            kb_sources, kb_debug = await self._knowledge_context.fetch_sources(
                use_knowledge=use_knowledge,
                search_query=search_query,
                query_embedding=query_embedding,
                ctx=ctx,
                is_complex=is_complex,
                is_question_like=is_question_like,
                is_policy_intent=is_policy_intent,
                policy_topic_count=policy_topic_count,
                max_sub_questions=max_sub_questions,
                run_id=run_id,
            )
            self._add_latency_span(spans, "vector_search_ms", (time.perf_counter() - kb_fetch_started) * 1000.0)
            debug_meta.update(kb_debug)

        sources: List[KnowledgeSource] = []

        # Override show_products_flag if we found an EXACT match (smart search)
        if best_distance is not None and best_distance == 0.0 and product_cards:
            logger.info("Forcing show_products=True due to exact SKU/MasterCode match")
            show_products_flag = True
            intent = "search_specific"

        top_products, product_sources, product_fallback_used = ProductContextAssembler.select_primary_products(
            product_cards=product_cards,
            best_distance=best_distance,
            show_products_flag=show_products_flag,
            intent=intent,
            default_threshold=float(getattr(settings, "PRODUCT_DISTANCE_THRESHOLD", 0.45)),
            allow_fallback_products=intent in {"browse_products", "search_specific"},
        )
        sources.extend(product_sources)
        if product_fallback_used:
            debug_meta["product_fallback_used"] = True

        # 4b. Cross-sell accessories (e.g., barbell attachments)
        cross_sell_products: List[ProductCard] = []
        cross_sell_label: Optional[str] = None
        cross_sell_used = False
        cross_sell_mode = str(getattr(settings, "CHAT_CROSS_SELL_MODE", "off") or "off").strip().lower()
        if top_products and cross_sell_mode == "inline":
            primary_type = self._infer_primary_jewelry_type(products=top_products, query_text=search_query)
            cross_sell_query = self._build_cross_sell_query(primary_type or "")
            cross_sell_label = self._build_cross_sell_label(primary_type or "")
            if cross_sell_query:
                cross_embedding: Optional[List[float]] = None
                cross_embed_started = time.perf_counter()
                try:
                    cross_embedding = await self._run_external_call(
                        external_state=external_state,
                        call_name="embedding_cross_sell",
                        call_factory=lambda: llm_service.generate_embedding(cross_sell_query),
                        run_id=run_id,
                        debug_meta=debug_meta,
                    )
                except Exception as exc:
                    debug_meta["cross_sell_embedding_error"] = str(exc)
                    self._log_event(
                        run_id=run_id,
                        location="chat_service.cross_sell.embedding_error",
                        data={"error_type": type(exc).__name__, "error": str(exc)},
                    )
                finally:
                    self._add_latency_span(spans, "vector_search_ms", (time.perf_counter() - cross_embed_started) * 1000.0)

                if cross_embedding is not None:
                    try:
                        cross_search_started = time.perf_counter()
                        cross_cards, _cross_distances, _cross_best, _cross_map = await self.search_products(
                            cross_embedding,
                            limit=int(getattr(settings, "CHAT_VECTOR_TOP_K", 12)),
                            run_id=run_id,
                        )
                        cross_search_elapsed = (time.perf_counter() - cross_search_started) * 1000.0
                        prev_vector_ms = float(spans.get("vector_search_ms", 0.0) or 0.0)
                        self._merge_catalog_metrics_into_spans(spans)
                        if float(spans.get("vector_search_ms", 0.0) or 0.0) <= prev_vector_ms:
                            self._add_latency_span(spans, "vector_search_ms", cross_search_elapsed)

                        exclude_ids = {str(p.id) for p in top_products}
                        cross_sell_products = self._filter_cross_sell_products(
                            products=cross_cards,
                            exclude_type=primary_type,
                            exclude_ids=exclude_ids,
                            limit=3,
                        )
                        if cross_sell_products:
                            remaining = max(0, 10 - len(top_products))
                            added = cross_sell_products[:remaining] if remaining else []
                            if added:
                                top_products.extend(added)
                                accessory_text = "\n".join(
                                    [
                                        f"TYPE: {p.attributes.get('jewelry_type', 'Accessory')}, NAME: {p.name}, SKU: {p.sku}, PRICE: {p.price} {p.currency}"
                                        for p in added
                                    ]
                                )
                                sources.append(
                                    KnowledgeSource(
                                        source_id="product_cross_sell",
                                        title="Compatible Accessories",
                                        content_snippet=f"Related accessories customers often pair with these items:\n{accessory_text}",
                                        relevance=0.35,
                                    )
                                )
                                debug_meta["cross_sell_used"] = True
                                cross_sell_used = True
                    except Exception as exc:
                        debug_meta["cross_sell_search_error"] = str(exc)
                        self._log_event(
                            run_id=run_id,
                            location="chat_service.cross_sell.search_error",
                            data={"error_type": type(exc).__name__, "error": str(exc)},
                        )
        else:
            debug_meta["cross_sell_skipped"] = True

        sources.extend(kb_sources)

        max_answer_sources = int(getattr(settings, "RAG_MAX_SOURCES_IN_RESPONSE", 5))
        sources_for_answer = sources[:max_answer_sources]
        debug_meta["retrieved_source_count"] = len(sources)
        debug_meta["answer_source_count"] = len(sources_for_answer)

        # 4. Generate Response (Strict RAG)
        deterministic_product_reply = bool(top_products) and bool(use_products) and not bool(use_knowledge) and not bool(detail_mode_enabled)
        if deterministic_product_reply:
            reply_data = self._build_deterministic_product_reply_data(
                products=top_products,
                attribute_filters=detail_request.attribute_filters,
            )
            debug_meta["reply_mode"] = "deterministic_product"
            debug_meta["llm_answer_skipped"] = True
        else:
            llm_answer_started = time.perf_counter()
            try:
                reply_data = await self._run_external_call(
                    external_state=external_state,
                    call_name="llm_answer",
                    call_factory=lambda: self.synthesize_answer(
                        question=text,
                        sources=sources_for_answer,
                        reply_language=reply_language,
                        history=history_for_llm,
                        run_id=run_id,
                    ),
                    run_id=run_id,
                    debug_meta=debug_meta,
                )
                debug_meta["reply_mode"] = "llm"
            except Exception:
                route_kind = "vague" if self._looks_vague_query(text) else (
                    "knowledge_query" if use_knowledge else "browse_products"
                )
                response = await self._build_route_fallback_response(
                    conversation_id=conversation_id_value,
                    route_kind=route_kind,
                    reason=str(external_state.get("budget_exceeded_reason") or ExternalBudgetExceededReason.EXTERNAL_CONNECTIVITY.value),
                    user_text=text,
                    reply_language=reply_language,
                    target_currency=target_currency,
                    debug_meta=debug_meta,
                    product_carousel=list(top_products[:3]) if top_products else [],
                )
                self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - llm_answer_started) * 1000.0)
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
            self._add_latency_span(spans, "llm_answer_ms", (time.perf_counter() - llm_answer_started) * 1000.0)

        if bool(getattr(settings, "CHAT_LLM_RENDER_ONLY_GUARD", True)):
            debug_meta["llm_render_only_guard"] = True
        reply_data = await self._ensure_reply_consistency_with_products(
            reply_data=reply_data,
            has_products=bool(top_products),
            reply_language=reply_language,
            run_id=run_id,
        )
        reply_data, sku_guard_triggered = self._enforce_llm_sku_guard(
            reply_data=reply_data,
            product_cards=top_products,
        )
        if sku_guard_triggered:
            debug_meta["llm_sku_guard_triggered"] = True

        # 5. Render
        follow_up_questions = []
        if top_products:
            follow_up_questions = self._build_product_follow_up_questions(
                products=top_products,
                attribute_filters=detail_request.attribute_filters,
                user_text=text,
                limit=4,
            )
            if self._has_product_context(
                attribute_filters=detail_request.attribute_filters,
                user_text=text,
            ):
                debug_meta["follow_up_generation"] = "product_context"
            else:
                debug_meta["follow_up_generation"] = "product_attribute_fallback"
        elif reply_data.get("recommended_questions"):
            # Knowledge/general path can still use LLM-proposed suggestions.
            follow_up_questions = list(reply_data["recommended_questions"])
            debug_meta["follow_up_generation"] = "llm"

        if cross_sell_used and cross_sell_label:
            accessory_question = f"Show {cross_sell_label}"
            if accessory_question not in follow_up_questions:
                follow_up_questions.append(accessory_question)

        if top_products:
            out_of_stock_count = 0
            for product in top_products:
                stock_value = str(product.stock_status or "").strip().lower()
                if stock_value in {"out_of_stock", "stockstatus.out_of_stock"}:
                    out_of_stock_count += 1
            if out_of_stock_count * 2 >= len(top_products):
                in_stock_question = "Show similar in-stock items"
                if in_stock_question not in follow_up_questions:
                    follow_up_questions.append(in_stock_question)

        # Enforce limit of 5
        if len(follow_up_questions) > 5:
            follow_up_questions = follow_up_questions[:5]

        response_build_started = time.perf_counter()
        response = await self._response_renderer.render(
            conversation_id=conversation_id_value,
            route="rag_strict",
            reply_data=reply_data,
            product_carousel=top_products,
            follow_up_questions=follow_up_questions,
            sources=sources_for_answer,
            debug=debug_meta,
            reply_language=reply_language,
            target_currency=target_currency,
            user_text=text,
            apply_polish=False,
        )
        self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)

        if response.sources:
            payload = {
                "reply_text": response.reply_text,
                "carousel_msg": response.carousel_msg or "",
                "product_carousel": [p.dict() for p in response.product_carousel],
                "follow_up_questions": list(response.follow_up_questions or []),
                "intent": response.intent,
                "sources": [s.dict() for s in response.sources],
                "view_button_text": response.view_button_text,
                "material_label": response.material_label,
                "jewelry_type_label": response.jewelry_type_label,
            }
            for p in payload["product_carousel"]:
                if p.get("id"):
                    p["id"] = str(p["id"])
            await semantic_cache_service.save_hit(
                self.db,
                query_text=search_query,
                query_embedding=query_embedding or [],
                response_json=payload,
                reply_language=reply_language,
                target_currency=target_currency,
            )

        token_usage = llm_service.consume_token_usage()
        return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
    except Exception as exc:
        token_usage = llm_service.consume_token_usage()
        _apply_external_debug()
        self._log_latency_error(
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_enabled,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
            error=exc,
        )
        raise
