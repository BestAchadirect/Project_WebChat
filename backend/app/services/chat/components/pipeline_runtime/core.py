from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.prompts.ambiguity import ambiguity_blocks_retrieval
from app.schemas.chat import (
    ChatRequest,
)
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.chat.runtime import conversation_state
from app.services.chat.presentation import product_presentation
from app.services.chat.routing import routing_policy
from app.services.chat.components.cache import ComponentCache
from app.services.chat.components.field_resolver import FieldDependencyResolver
from app.services.chat.components.pipeline_runtime.state import (
    ComponentPipelineResult,
    PipelineDecisionRuntimeState,
    PipelineRetrievalState,
    PipelineWorkflowState,
)
from app.services.chat.components.pipeline_runtime.policy import (
    CONTACT_KNOWLEDGE_TERMS,
    DETAIL_CLARIFY_FIELDS,
    FALLBACK_VALID_HINTS,
    HIGH_RISK_KNOWLEDGE_TERMS,
    KNOWLEDGE_UNAVAILABLE_MESSAGE,
    LOCATION_KNOWLEDGE_TERMS,
    OFF_TOPIC_REDIRECT_OPTIONS,
    PAYMENT_KNOWLEDGE_TERMS,
    REFUND_KNOWLEDGE_TERMS,
    SHIPPING_KNOWLEDGE_TERMS,
    WARRANTY_KNOWLEDGE_TERMS,
)
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.knowledge.retrieval import KnowledgeRetrievalService
from app.services.chat.components.pipeline_runtime.setup import PipelineSetupMixin
from app.services.chat.components.pipeline_runtime.workflow_handlers import PipelineWorkflowHandlersMixin
from app.services.chat.components.pipeline_runtime.workflow_policy import PipelineWorkflowPolicyMixin
from app.services.chat.retrieval.pipeline_support import PipelineSupportMixin
from app.services.chat.presentation.pipeline_presentation import PipelinePresentationMixin
from app.services.chat.parsing.llm_attribute_extractor import infer_attribute_list_target
from app.services.chat.routing.contracts import DecisionState


class ComponentPipeline(
    PipelineSetupMixin,
    PipelineWorkflowPolicyMixin,
    PipelineWorkflowHandlersMixin,
    PipelineSupportMixin,
    PipelinePresentationMixin,
):
    _DETAIL_CLARIFY_FIELDS = DETAIL_CLARIFY_FIELDS

    _HIGH_RISK_KNOWLEDGE_TERMS = HIGH_RISK_KNOWLEDGE_TERMS

    _CONTACT_KNOWLEDGE_TERMS = CONTACT_KNOWLEDGE_TERMS

    _LOCATION_KNOWLEDGE_TERMS = LOCATION_KNOWLEDGE_TERMS

    _SHIPPING_KNOWLEDGE_TERMS = SHIPPING_KNOWLEDGE_TERMS

    _REFUND_KNOWLEDGE_TERMS = REFUND_KNOWLEDGE_TERMS

    _PAYMENT_KNOWLEDGE_TERMS = PAYMENT_KNOWLEDGE_TERMS

    _WARRANTY_KNOWLEDGE_TERMS = WARRANTY_KNOWLEDGE_TERMS

    _KNOWLEDGE_UNAVAILABLE_MESSAGE = KNOWLEDGE_UNAVAILABLE_MESSAGE

    _FALLBACK_VALID_HINTS = FALLBACK_VALID_HINTS

    _OFF_TOPIC_REDIRECT_OPTIONS = OFF_TOPIC_REDIRECT_OPTIONS

    def __init__(
            self,
            *,
            db: AsyncSession,
            catalog_search: CatalogProductSearchService,
            knowledge_retrieval: KnowledgeRetrievalService,
            component_cache: ComponentCache | None = None,
            redis_cache: ComponentCache | None = None,
        ):
            self.db = db
            self._catalog_search = catalog_search
            self._knowledge_retrieval = knowledge_retrieval
            self._component_cache = component_cache or redis_cache
            self._field_resolver = FieldDependencyResolver(db=db)

    async def run(
            self,
            *,
            request: ChatRequest,
            conversation_id: int,
            run_id: str,
            route_decision_override: Optional[routing_policy.WorkflowDecision] = None,
            detail_override: Any | None = None,
            llm_call_count_override: int = 0,
            routing_selection_source: str = "",
            internal_workflow_override: str = "",
            decision_state_override: Optional[DecisionState] = None,
            channel: str = "widget",
        ) -> ComponentPipelineResult:
            started = time.perf_counter()
            text = str(request.message or "").strip()
            locale = str(request.locale or "en-US")
            client_action = str(getattr(request, "client_action", "") or "").strip().lower()
            client_action_payload = dict(getattr(request, "client_action_payload", {}) or {})
            setup = await self._prepare_pipeline_run(
                text=text,
                channel=channel,
                conversation_id=conversation_id,
                route_decision_override=route_decision_override,
                detail_override=detail_override,
                llm_call_count_override=llm_call_count_override,
                routing_selection_source=routing_selection_source,
                internal_workflow_override=internal_workflow_override,
                decision_state_override=decision_state_override,
                client_action=client_action,
                client_action_payload=client_action_payload,
            )
            normalized_text = setup.normalized_text
            detail = setup.detail
            conversation_state_enabled = setup.conversation_state_enabled
            state_working = setup.state_working
            catalog_pagination_requested = setup.catalog_pagination_requested
            catalog_pagination_stale_requested = setup.catalog_pagination_stale_requested
            catalog_pagination_offset = setup.catalog_pagination_offset
            catalog_pagination_state_offset = setup.catalog_pagination_state_offset
            catalog_pagination_limit = setup.catalog_pagination_limit
            catalog_pagination_query_key = setup.catalog_pagination_query_key
            catalog_pagination_query_ids = setup.catalog_pagination_query_ids
            sku_tokens = setup.sku_tokens
            unique_sku_tokens = setup.unique_sku_tokens
            route_decision = setup.route_decision
            workflow = setup.workflow
            internal_workflow = str(setup.internal_workflow or workflow)
            store_overview_request = setup.store_overview_request
            knowledge_workflow = setup.knowledge_workflow
            fallback_workflow = setup.fallback_workflow
            source = setup.source
            decision_state = setup.decision_state
            search_plan = setup.search_plan

            execution_state = setup.execution_state
            debug_meta = execution_state.debug_meta
            spans = execution_state.spans
            external_call_counts = execution_state.external_call_counts
            llm_calls = int(setup.llm_call_count or 0)
            embedding_calls = 0
            tone_controller = setup.tone_controller
            needs_knowledge = bool(route_decision.needs_knowledge)
            knowledge_query = str(route_decision.knowledge_query or "").strip()

            if conversation_state_enabled and state_working is not None:
                state_working = conversation_state.apply_workflow_update(
                    state_working,
                    workflow=workflow,
                    refined_query=text,
                    attribute_filters=detail.attribute_filters,
                )

            workflow_started = time.perf_counter()
            spans["workflow_routing_ms"] = (time.perf_counter() - workflow_started) * 1000.0

            query_summary = text if text else "Please provide a question."
            display_limit = product_presentation.PRODUCT_DISPLAY_LIMIT
            result_fetch_limit = max(display_limit * 30, 120)
            detail_semantic_hints = [
                str(item or "").strip()
                for item in list(getattr(detail, "semantic_hints", []) or [])
                if str(item or "").strip()
            ]
            detail_clarify_focus = str(getattr(detail, "clarify_focus", "") or "").strip()
            detail_parse_failed = bool(getattr(detail, "parse_failed", False))
            attribute_list_target = ""
            attribute_list_target_source = ""
            if (
                workflow == "catalog"
                and not detail_parse_failed
                and not list(sku_tokens or [])
                and not dict(getattr(detail, "attribute_filters", {}) or {})
                and not ambiguity_blocks_retrieval(detail_clarify_focus)
            ):
                attribute_list_result = await infer_attribute_list_target(
                    user_text=text,
                    workflow=workflow,
                )
                attribute_list_confidence = float(getattr(attribute_list_result, "confidence", 0.0) or 0.0)
                if attribute_list_confidence >= float(getattr(setup.runtime_capabilities, "chat_attribute_interpretation_min_confidence", 0.55) or 0.55):
                    attribute_list_target = str(attribute_list_result.target or "").strip().lower()
                    attribute_list_target_source = "llm" if attribute_list_target else "none"
                if int(attribute_list_result.llm_call_count or 0) > 0:
                    llm_calls += int(attribute_list_result.llm_call_count or 0)
                    external_call_counts["llm_attribute_list_target"] = int(attribute_list_result.llm_call_count or 0)
                debug_meta.update(dict(attribute_list_result.debug or {}))
            if attribute_list_target_source:
                debug_meta["attribute_list_target_source"] = attribute_list_target_source
            state = PipelineWorkflowState(
                retrieval=PipelineRetrievalState(source=source),
                decision=PipelineDecisionRuntimeState(
                    runtime_capabilities=setup.runtime_capabilities,
                    search_plan=search_plan,
                    internal_workflow=internal_workflow,
                    intent=str(getattr(decision_state, "intent", "") or ""),
                    subintent=str(getattr(decision_state, "subintent", "") or ""),
                    user_goal=str(getattr(decision_state, "user_goal", "") or ""),
                    product_query=str(getattr(decision_state, "product_query", "") or ""),
                    response_policy=str(getattr(decision_state, "response_policy", "") or ""),
                    clarify_question=str(getattr(decision_state, "clarify_question", "") or ""),
                    pending_task_type=str(getattr(decision_state, "pending_task_type", "") or ""),
                    missing_slot=str(getattr(decision_state, "missing_slot", "") or ""),
                    intent_confidence=float(getattr(decision_state, "intent_confidence", 0.0) or 0.0),
                    answerability=str(getattr(decision_state, "answerability", "none") or "none"),
                ),
            )
            context_price_followup_possible = bool(
                workflow == "catalog"
                and list(debug_meta.get("conversation_last_product_ids") or [])
                and str(getattr(decision_state, "missing_slot", "") or "").strip().lower() == "product_anchor"
                and str(getattr(decision_state, "pending_task_type", "") or "").strip().lower()
                in {"compare_price", "find_cheaper_products"}
            )
            context_related_followup_possible = bool(
                workflow == "catalog"
                and list(debug_meta.get("conversation_last_product_ids") or [])
                and self._looks_like_related_product_followup(text=text)
            )
            product_anchor_present = bool(debug_meta.get("catalog_product_anchor_present"))
            unresolved_attributes = [
                dict(item)
                for item in list(debug_meta.get("unresolved_attributes") or [])
                if isinstance(item, dict)
            ]
            if (
                workflow == "catalog"
                and unresolved_attributes
                and not catalog_pagination_requested
                and not bool(debug_meta.get("clarification_loop_stop"))
            ):
                missing_slots = [
                    str(item.get("attribute") or "").strip()
                    for item in unresolved_attributes
                    if str(item.get("attribute") or "").strip()
                ]
                focus = str((missing_slots or [""])[0] or "").strip().lower()
                state.decision.ambiguity_reason = "semantic_concept_unclear"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.presentation.canonical_products = []
                state.catalog.product_ids = []
                state.catalog.query_product_ids = []
                state.retrieval.result_count = 0
                state.retrieval.source = ComponentSource.ERROR
                debug_meta["catalog_retrieval_blocked_reason"] = "unresolved_hard_constraint"
                debug_meta["clarify_reason"] = state.decision.ambiguity_reason
                debug_meta["clarify_missing_slots"] = list(dict.fromkeys(missing_slots))
                debug_meta["semantic_hint_clarify_used"] = True
                if focus:
                    try:
                        detail = replace(detail, clarify_focus=focus)
                    except Exception:
                        debug_meta["semantic_hint_clarify_focus"] = focus
            if (
                workflow == "catalog"
                and unresolved_attributes
                and bool(debug_meta.get("clarification_loop_stop"))
            ):
                debug_meta["clarification_loop_fallback_used"] = True
                debug_meta["clarification_loop_fallback_policy"] = "broad_safe_results"
            if (
                workflow == "catalog"
                and not state.decision.ambiguity_reason
                and not catalog_pagination_requested
                and not context_price_followup_possible
                and not context_related_followup_possible
                and not dict(getattr(detail, "attribute_filters", {}) or {})
                and "product_anchor" in str(getattr(decision_state, "missing_slot", "") or "").strip().lower()
                and (
                    str(getattr(decision_state, "response_policy", "") or "").strip().lower() == "ask_clarifying_question"
                    or str(getattr(decision_state, "pending_task_type", "") or "").strip()
                    or str(getattr(decision_state, "clarify_question", "") or "").strip()
                )
                and not product_anchor_present
            ):
                state.decision.ambiguity_reason = "pending_task_missing_slot"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.presentation.canonical_products = []
                state.catalog.product_ids = []
                state.catalog.query_product_ids = []
                state.retrieval.result_count = 0
                state.retrieval.source = ComponentSource.ERROR
                debug_meta["catalog_retrieval_blocked_reason"] = "llm_requested_product_anchor_clarification"
                debug_meta["clarify_reason"] = state.decision.ambiguity_reason
            if (
                workflow == "catalog"
                and not state.decision.ambiguity_reason
                and not catalog_pagination_requested
                and detail_parse_failed
                and not store_overview_request
            ):
                state.decision.ambiguity_reason = "semantic_concept_unclear"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.presentation.canonical_products = []
                state.catalog.product_ids = []
                state.catalog.query_product_ids = []
                state.retrieval.result_count = 0
                state.retrieval.source = ComponentSource.ERROR
                debug_meta["catalog_retrieval_blocked_reason"] = "detail_extraction_failed"
                debug_meta["semantic_guardrail_reason"] = "detail_extraction_failed"
                debug_meta["semantic_hint_clarify_used"] = True
                debug_meta["clarify_reason"] = state.decision.ambiguity_reason
            if (
                not catalog_pagination_requested
                and not state.decision.ambiguity_reason
                and not dict(getattr(detail, "attribute_filters", {}) or {})
                and ambiguity_blocks_retrieval(getattr(detail, "clarify_focus", ""))
            ):
                state.decision.ambiguity_reason = (
                    "semantic_concept_unclear"
                )
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.presentation.canonical_products = []
                state.retrieval.result_count = 0
                debug_meta["semantic_guardrail_reason"] = "semantic_hint_clarify"
                debug_meta["semantic_hint_clarify_used"] = True
                debug_meta["clarify_reason"] = state.decision.ambiguity_reason
            if catalog_pagination_stale_requested:
                state.catalog.pagination_requested = True
                state.catalog.pagination_offset = catalog_pagination_offset
                state.catalog.pagination_limit = catalog_pagination_limit
                state.catalog.query_cache_key = catalog_pagination_query_key
                state.catalog.query_product_ids = list(catalog_pagination_query_ids or [])
                state.decision.ambiguity_reason = "pagination_stale"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.presentation.canonical_products = []
                state.catalog.product_ids = []
                state.retrieval.result_count = 0
                state.retrieval.source = ComponentSource.ERROR
                debug_meta["catalog_pagination_requested"] = True
                debug_meta["catalog_pagination_error"] = "stale_pagination_state"
                debug_meta["catalog_pagination_state_offset"] = int(catalog_pagination_state_offset or 0)
                debug_meta["catalog_pagination_query_text"] = str(text or "").strip()
            if catalog_pagination_requested and not catalog_pagination_stale_requested:
                await self._handle_catalog_pagination_workflow(
                    state=state,
                    text=text,
                    locale=locale,
                    workflow=workflow,
                    detail=detail,
                    store_overview_request=store_overview_request,
                    unique_sku_tokens=unique_sku_tokens,
                    display_limit=display_limit,
                    pagination_query_cache_key=catalog_pagination_query_key,
                    pagination_query_product_ids=catalog_pagination_query_ids,
                    pagination_offset=catalog_pagination_offset,
                    pagination_limit=catalog_pagination_limit,
                    debug_meta=debug_meta,
                    spans=spans,
                    external_call_counts=external_call_counts,
                )
            else:
                terminal_handled, terminal_llm_calls = await self._handle_terminal_workflows(
                    state=state,
                    text=text,
                    locale=locale,
                    workflow=workflow,
                    internal_workflow=internal_workflow,
                    debug_meta=debug_meta,
                    spans=spans,
                    external_call_counts=external_call_counts,
                )
                llm_calls += int(terminal_llm_calls or 0)
                if not terminal_handled:
                    await self._handle_pre_catalog_workflows(
                        state=state,
                        workflow=workflow,
                        store_overview_request=store_overview_request,
                        result_fetch_limit=result_fetch_limit,
                        debug_meta=debug_meta,
                        spans=spans,
                    )
                    if workflow == "catalog" and not state.catalog.handled_attribute_list:
                        if attribute_list_target and not state.decision.ambiguity_reason:
                            await self._handle_attribute_list_workflow(
                                state=state,
                                text=text,
                                workflow=workflow,
                                detail=detail,
                                attribute_list_target=attribute_list_target,
                                debug_meta=debug_meta,
                                spans=spans,
                                external_call_counts=external_call_counts,
                            )
                        if not state.catalog.handled_attribute_list:
                            await self._handle_catalog_workflow(
                                state=state,
                                text=text,
                                locale=locale,
                                workflow=workflow,
                                detail=detail,
                                store_overview_request=store_overview_request,
                                unique_sku_tokens=unique_sku_tokens,
                                display_limit=display_limit,
                                result_fetch_limit=result_fetch_limit,
                                normalized_text=normalized_text,
                                debug_meta=debug_meta,
                                spans=spans,
                                external_call_counts=external_call_counts,
                            )
                        if needs_knowledge and not state.decision.ambiguity_reason:
                            await self._handle_mixed_knowledge_enrichment(
                                state=state,
                                text=text,
                                locale=locale,
                                run_id=run_id,
                                store_overview_request=store_overview_request,
                                normalized_text=normalized_text,
                                preferred_query=knowledge_query,
                                debug_meta=debug_meta,
                                spans=spans,
                                external_call_counts=external_call_counts,
                            )
                    elif knowledge_workflow:
                        if internal_workflow == "company_info":
                            await self._handle_company_info_workflow(
                                state=state,
                                text=text,
                                locale=locale,
                                run_id=run_id,
                                store_overview_request=store_overview_request,
                                normalized_text=normalized_text,
                                preferred_query=knowledge_query,
                                debug_meta=debug_meta,
                                spans=spans,
                                external_call_counts=external_call_counts,
                            )
                        else:
                            await self._handle_knowledge_workflow(
                                state=state,
                                text=text,
                                locale=locale,
                                run_id=run_id,
                                store_overview_request=store_overview_request,
                                normalized_text=normalized_text,
                                preferred_query=knowledge_query,
                                debug_meta=debug_meta,
                                spans=spans,
                                external_call_counts=external_call_counts,
                            )
                    elif fallback_workflow:
                        self._handle_fallback_workflow(
                            state=state,
                            text=text,
                            route_decision=route_decision,
                            attribute_filters=dict(detail.attribute_filters or {}),
                            sku_tokens=unique_sku_tokens,
                        )

            return await self._finalize_pipeline_result(
                started=started,
                conversation_id=conversation_id,
                text=text,
                locale=locale,
                workflow=workflow,
                route_decision=route_decision,
                routing_selection_source=routing_selection_source,
                internal_workflow=internal_workflow,
                detail=detail,
                sku_tokens=sku_tokens,
                query_summary=query_summary,
                state=state,
                debug_meta=debug_meta,
                tone_snapshot=lambda: {
                    "recent": list(tone_controller.recent),
                    "key": tone_controller.latest_key,
                    "variant_id": tone_controller.latest_variant_id,
                    "style": tone_controller.latest_style,
                    "anti_repeat_applied": bool(tone_controller.latest_anti_repeat),
                    "repeat_hit": int(tone_controller.repeat_hit_count),
                    "filler_stripped": int(tone_controller.filler_stripped_count),
                },
                llm_calls=llm_calls,
                embedding_calls=embedding_calls,
                external_call_counts=external_call_counts,
                spans=spans,
                knowledge_workflow=knowledge_workflow,
                conversation_state_enabled=conversation_state_enabled,
                state_working=state_working,
            )
