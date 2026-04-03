from __future__ import annotations

import logging
import time
from typing import Any, Dict, Sequence

from app.core.config import settings
from app.services.ai.llm_service import llm_service
from app.services.chat.routing import routing_policy
from app.services.chat.components.cache import stable_cache_key
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.chat.text_normalization import normalize_user_text

logger = logging.getLogger(__name__)


class PipelineWorkflowKnowledgeMixin:
    async def _resolve_knowledge_payload(
            self,
            *,
            text: str,
            locale: str,
            run_id: str,
            store_overview_request: bool,
            normalized_text: str,
            preferred_query: str = "",
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> Dict[str, Any]:
            knowledge_error_message = ""
            knowledge_query = str(preferred_query or "").strip() or str(text or "").strip()
            knowledge_query_normalized = normalize_user_text(knowledge_query) or normalized_text
            knowledge_sources = []
            knowledge_answer = ""
            capabilities = build_chat_runtime_capabilities()
            high_risk_guard_enabled = bool(capabilities.chat_knowledge_high_risk_guard_enabled)
            knowledge_is_high_risk = high_risk_guard_enabled and self._is_high_risk_knowledge_request(text=knowledge_query)
            min_knowledge_relevance = float(capabilities.chat_knowledge_min_relevance)
            if int(capabilities.chat_hard_max_embeddings_per_request) > 0:
                try:
                    embed_started = time.perf_counter()
                    embedding = await llm_service.generate_embedding(knowledge_query)
                    spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                    external_call_counts["embedding_query"] = int(external_call_counts.get("embedding_query", 0)) + 1
                    knowledge_started = time.perf_counter()
                    knowledge_sources = await self._knowledge_retrieval.search(
                        query_text=knowledge_query,
                        query_embedding=embedding,
                        limit=5,
                        store_overview_request=store_overview_request,
                        run_id=run_id,
                    )
                    spans["vector_search_ms"] += (time.perf_counter() - knowledge_started) * 1000.0
                except Exception as exc:
                    debug_meta["component_knowledge_search_error"] = str(exc)
                    knowledge_error_message = self._KNOWLEDGE_UNAVAILABLE_MESSAGE

            top_knowledge_relevance = max(
                (float(getattr(source, "relevance", 0.0) or 0.0) for source in list(knowledge_sources or [])),
                default=0.0,
            )
            knowledge_sources_weak = self._knowledge_sources_are_weak(
                sources=knowledge_sources,
                min_relevance=min_knowledge_relevance,
            )
            debug_meta["knowledge_sources_weak"] = knowledge_sources_weak
            debug_meta["knowledge_is_high_risk"] = knowledge_is_high_risk
            debug_meta["knowledge_high_risk_guard_enabled"] = high_risk_guard_enabled
            debug_meta["knowledge_min_relevance"] = min_knowledge_relevance
            debug_meta["knowledge_top_relevance"] = top_knowledge_relevance
            debug_meta["knowledge_query_text"] = knowledge_query
            skip_knowledge_answer = bool(
                knowledge_is_high_risk and (bool(knowledge_error_message) or knowledge_sources_weak)
            )
            debug_meta["knowledge_answer_skipped"] = skip_knowledge_answer

            if not skip_knowledge_answer and not knowledge_error_message:
                llm_cache_key = stable_cache_key(
                    f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:knowledge_answer",
                    {
                        "q": knowledge_query_normalized,
                        "locale": locale.lower(),
                        "source_ids": [source.source_id for source in knowledge_sources],
                        "store_overview_request": bool(store_overview_request),
                    },
                )
                try:
                    llm_started = time.perf_counter()
                    knowledge_answer, from_cache = await self._knowledge_answer_once(
                        question=knowledge_query,
                        sources=knowledge_sources,
                        locale=locale,
                        store_overview_request=store_overview_request,
                        llm_cache_key=llm_cache_key,
                        debug_meta=debug_meta,
                    )
                    spans["llm_answer_ms"] += (time.perf_counter() - llm_started) * 1000.0
                    if not from_cache:
                        external_call_counts["llm_answer"] = int(external_call_counts.get("llm_answer", 0)) + 1
                except Exception as exc:
                    debug_meta["component_knowledge_answer_error"] = str(exc)
                    knowledge_error_message = self._KNOWLEDGE_UNAVAILABLE_MESSAGE

            ambiguity_reason = ""
            if knowledge_error_message and knowledge_is_high_risk:
                ambiguity_reason = "knowledge_unavailable"
            elif knowledge_sources_weak and knowledge_is_high_risk:
                ambiguity_reason = "knowledge_needs_clarification"

            return {
                "knowledge_query": knowledge_query,
                "knowledge_sources": knowledge_sources,
                "knowledge_answer": knowledge_answer,
                "knowledge_error_message": knowledge_error_message,
                "knowledge_is_high_risk": knowledge_is_high_risk,
                "knowledge_sources_weak": knowledge_sources_weak,
                "min_knowledge_relevance": min_knowledge_relevance,
                "top_knowledge_relevance": top_knowledge_relevance,
                "skip_knowledge_answer": skip_knowledge_answer,
                "ambiguity_reason": ambiguity_reason,
            }

    async def _handle_knowledge_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            run_id: str,
            store_overview_request: bool,
            normalized_text: str,
            preferred_query: str = "",
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> None:
            state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            payload = await self._resolve_knowledge_payload(
                text=text,
                locale=locale,
                run_id=run_id,
                store_overview_request=store_overview_request,
                normalized_text=normalized_text,
                preferred_query=preferred_query,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            state.knowledge_sources = list(payload["knowledge_sources"] or [])
            state.knowledge_answer = str(payload["knowledge_answer"] or "")
            knowledge_error_message = str(payload["knowledge_error_message"] or "")
            knowledge_is_high_risk = bool(payload["knowledge_is_high_risk"])
            knowledge_sources_weak = bool(payload["knowledge_sources_weak"])
            min_knowledge_relevance = float(payload["min_knowledge_relevance"] or 0.0)
            top_knowledge_relevance = float(payload["top_knowledge_relevance"] or 0.0)

            if knowledge_error_message and knowledge_is_high_risk:
                state.ambiguity_reason = "knowledge_unavailable"
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.retrieval_source = ComponentSource.KNOWLEDGE
                state.result_count = 0
                debug_meta["component_knowledge_fail_soft"] = True
                logger.debug("High-risk knowledge request downgraded to clarification because retrieval failed")
            elif knowledge_sources_weak and knowledge_is_high_risk:
                state.ambiguity_reason = "knowledge_needs_clarification"
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.retrieval_source = ComponentSource.KNOWLEDGE
                state.result_count = 0
                debug_meta["component_knowledge_needs_clarification"] = True
                logger.debug(
                    "High-risk knowledge request downgraded to clarification because top relevance %.2f is below %.2f",
                    top_knowledge_relevance,
                    min_knowledge_relevance,
                )
            elif knowledge_error_message:
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.ERROR]
                state.retrieval_source = ComponentSource.ERROR
                state.result_count = 0
                debug_meta["component_knowledge_fail_soft"] = True
            else:
                state.retrieval_source = ComponentSource.KNOWLEDGE
                state.result_count = len(state.knowledge_sources)
            state.knowledge_error_message = knowledge_error_message

    async def _handle_mixed_knowledge_enrichment(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            run_id: str,
            store_overview_request: bool,
            normalized_text: str,
            preferred_query: str = "",
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> None:
            payload = await self._resolve_knowledge_payload(
                text=text,
                locale=locale,
                run_id=run_id,
                store_overview_request=store_overview_request,
                normalized_text=normalized_text,
                preferred_query=preferred_query,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            debug_meta["mixed_intent_knowledge_requested"] = True
            debug_meta["mixed_intent_knowledge_query"] = str(payload["knowledge_query"] or "")
            debug_meta["mixed_intent_knowledge_ambiguity_reason"] = str(payload["ambiguity_reason"] or "")

            if str(payload["ambiguity_reason"] or "").strip():
                debug_meta["mixed_intent_knowledge_used"] = False
                return
            if str(payload["knowledge_error_message"] or "").strip():
                debug_meta["mixed_intent_knowledge_used"] = False
                return
            if not str(payload["knowledge_answer"] or "").strip():
                debug_meta["mixed_intent_knowledge_used"] = False
                return

            state.knowledge_sources = list(payload["knowledge_sources"] or [])
            state.knowledge_answer = str(payload["knowledge_answer"] or "")
            if ComponentType.KNOWLEDGE_ANSWER not in state.selected_components:
                state.selected_components.append(ComponentType.KNOWLEDGE_ANSWER)
            debug_meta["mixed_intent_knowledge_used"] = True

    def _handle_fallback_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            route_decision: routing_policy.WorkflowDecision,
            attribute_filters: Dict[str, Any],
            sku_tokens: Sequence[str],
        ) -> None:
            state.ambiguity_reason = state.ambiguity_reason or self._fallback_subtype(
                user_text=text,
                route_reason=str(route_decision.reason or ""),
                attribute_filters=dict(attribute_filters or {}),
                sku_tokens=list(sku_tokens or []),
            )
            state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
            state.retrieval_source = ComponentSource.ERROR
            state.result_count = 0
