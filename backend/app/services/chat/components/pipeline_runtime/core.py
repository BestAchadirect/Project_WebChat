from __future__ import annotations

import time
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import (
    ChatRequest,
)
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.chat.runtime import conversation_state
from app.services.chat.presentation import product_presentation
from app.services.chat.routing import routing_policy
from app.services.chat.components.cache import RedisComponentCache
from app.services.chat.components.field_resolver import FieldDependencyResolver
from app.services.chat.components.pipeline_runtime.state import (
    ComponentPipelineResult,
    PipelineWorkflowState,
)
from app.services.chat.components.pipeline_runtime.policy import (
    CONTACT_KNOWLEDGE_TERMS,
    DESIGN_DISCOVERY_TERMS,
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
from app.services.chat.retrieval.recommendation_service import RecommendationService
from app.services.knowledge.retrieval import KnowledgeRetrievalService
from app.services.chat.components.pipeline_runtime.setup import PipelineSetupMixin
from app.services.chat.components.pipeline_runtime.workflow_handlers import PipelineWorkflowHandlersMixin
from app.services.chat.components.pipeline_runtime.workflow_policy import PipelineWorkflowPolicyMixin
from app.services.chat.retrieval.pipeline_support import PipelineSupportMixin
from app.services.chat.presentation.pipeline_presentation import PipelinePresentationMixin


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

    _DESIGN_DISCOVERY_TERMS = DESIGN_DISCOVERY_TERMS

    _FALLBACK_VALID_HINTS = FALLBACK_VALID_HINTS

    _OFF_TOPIC_REDIRECT_OPTIONS = OFF_TOPIC_REDIRECT_OPTIONS

    def __init__(
            self,
            *,
            db: AsyncSession,
            catalog_search: CatalogProductSearchService,
            knowledge_retrieval: KnowledgeRetrievalService,
            redis_cache: RedisComponentCache,
        ):
            self.db = db
            self._catalog_search = catalog_search
            self._knowledge_retrieval = knowledge_retrieval
            self._redis_cache = redis_cache
            self._field_resolver = FieldDependencyResolver(db=db)
            self._recommendation_service = RecommendationService(db=db, catalog_search=catalog_search)

    async def run(
            self,
            *,
            request: ChatRequest,
            conversation_id: int,
            run_id: str,
            route_decision_override: Optional[routing_policy.WorkflowDecision] = None,
            routing_selection_source: str = "",
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
                routing_selection_source=routing_selection_source,
                client_action=client_action,
                client_action_payload=client_action_payload,
            )
            normalized_text = setup.normalized_text
            detail = setup.detail
            conversation_state_enabled = setup.conversation_state_enabled
            state_working = setup.state_working
            catalog_pagination_requested = setup.catalog_pagination_requested
            catalog_pagination_offset = setup.catalog_pagination_offset
            catalog_pagination_limit = setup.catalog_pagination_limit
            catalog_pagination_query_key = setup.catalog_pagination_query_key
            sku_tokens = setup.sku_tokens
            unique_sku_tokens = setup.unique_sku_tokens
            route_decision = setup.route_decision
            workflow = setup.workflow
            recommendation_requested = setup.recommendation_requested
            store_overview_request = setup.store_overview_request
            knowledge_workflow = setup.knowledge_workflow
            fallback_workflow = setup.fallback_workflow
            source = setup.source

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
            result_fetch_limit = max(display_limit * 6, 20)
            state = PipelineWorkflowState(retrieval_source=source)
            if catalog_pagination_requested:
                await self._handle_catalog_pagination_workflow(
                    state=state,
                    text=text,
                    locale=locale,
                    workflow=workflow,
                    detail=detail,
                    store_overview_request=store_overview_request,
                    unique_sku_tokens=unique_sku_tokens,
                    recommendation_requested=recommendation_requested,
                    display_limit=display_limit,
                    pagination_query_cache_key=catalog_pagination_query_key,
                    pagination_offset=catalog_pagination_offset,
                    pagination_limit=catalog_pagination_limit,
                    debug_meta=debug_meta,
                    spans=spans,
                    external_call_counts=external_call_counts,
                )
            else:
                _ = await self._handle_terminal_workflows(
                    state=state,
                    text=text,
                    workflow=workflow,
                    detail=detail,
                    unique_sku_tokens=unique_sku_tokens,
                    result_fetch_limit=result_fetch_limit,
                    conversation_id=conversation_id,
                    debug_meta=debug_meta,
                    spans=spans,
                    external_call_counts=external_call_counts,
                    tone_pick=tone_controller.pick,
                )
                await self._handle_pre_catalog_workflows(
                    state=state,
                    text=text,
                    workflow=workflow,
                    detail=detail,
                    store_overview_request=store_overview_request,
                    unique_sku_tokens=unique_sku_tokens,
                    result_fetch_limit=result_fetch_limit,
                    debug_meta=debug_meta,
                    spans=spans,
                )
                if workflow in {"catalog", "recommendation"}:
                    await self._handle_catalog_workflow(
                        state=state,
                        text=text,
                        locale=locale,
                        workflow=workflow,
                        detail=detail,
                        store_overview_request=store_overview_request,
                        unique_sku_tokens=unique_sku_tokens,
                        recommendation_requested=recommendation_requested,
                        display_limit=display_limit,
                        result_fetch_limit=result_fetch_limit,
                        normalized_text=normalized_text,
                        debug_meta=debug_meta,
                        spans=spans,
                        external_call_counts=external_call_counts,
                    )
                    if needs_knowledge and not state.ambiguity_reason:
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
                detail=detail,
                sku_tokens=sku_tokens,
                query_summary=query_summary,
                state=state,
                debug_meta=debug_meta,
                tone_pick=tone_controller.pick,
                tone_snapshot=tone_controller.snapshot,
                llm_calls=llm_calls,
                embedding_calls=embedding_calls,
                external_call_counts=external_call_counts,
                spans=spans,
                knowledge_workflow=knowledge_workflow,
                conversation_state_enabled=conversation_state_enabled,
                state_working=state_working,
            )
