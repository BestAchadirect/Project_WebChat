from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.chat.components.pipeline_runtime.state import PipelineExecutionState
from app.services.chat.components.types import ComponentSource
from app.services.chat.parsing import parser_rule_cache
from app.services.chat.parsing.detail_query_parser import DetailQueryParser
from app.services.chat.presentation import reply_tone
from app.services.chat.presentation import product_presentation
from app.services.chat.routing import routing_policy
from app.services.chat.routing.contracts import DecisionState
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities, build_chat_runtime_capabilities
from app.services.chat.runtime import alias_cache, conversation_state
from app.services.chat.text_normalization import normalize_user_text


@dataclass
class PipelineToneController:
    recent: List[Dict[str, Any]]
    latest_key: str = ""
    latest_variant_id: int = -1
    latest_style: str = ""
    latest_anti_repeat: bool = False
    repeat_hit_count: int = 0
    filler_stripped_count: int = 0


@dataclass
class PipelineRunSetup:
    normalized_text: str
    detail: Any
    conversation_state_enabled: bool
    state_working: Optional[Dict[str, Any]]
    catalog_pagination_requested: bool
    catalog_pagination_stale_requested: bool
    catalog_pagination_offset: int
    catalog_pagination_state_offset: int
    catalog_pagination_limit: int
    catalog_pagination_query_key: str
    catalog_pagination_query_ids: List[str]
    sku_tokens: List[str]
    unique_sku_tokens: List[str]
    route_decision: routing_policy.WorkflowDecision
    workflow: str
    store_overview_request: bool
    knowledge_workflow: bool
    fallback_workflow: bool
    source: ComponentSource
    execution_state: PipelineExecutionState
    tone_controller: PipelineToneController
    runtime_capabilities: ChatRuntimeCapabilities
    llm_call_count: int = 0
    internal_workflow: str = ""
    decision_state: Optional[DecisionState] = None


class PipelineSetupMixin:
    async def _prepare_pipeline_run(
            self,
            *,
            text: str,
            channel: str,
            conversation_id: int,
            route_decision_override: Optional[routing_policy.WorkflowDecision],
            detail_override: Any | None = None,
            llm_call_count_override: int = 0,
            routing_selection_source: str,
            internal_workflow_override: str = "",
            decision_state_override: Optional[DecisionState] = None,
            client_action: str = "",
            client_action_payload: Optional[Dict[str, Any]] = None,
        ) -> PipelineRunSetup:
            normalized_text = normalize_user_text(text)
            client_action_norm = str(client_action or "").strip().lower()
            client_action_payload = dict(client_action_payload or {})
            capabilities = build_chat_runtime_capabilities()

            alias_map = await alias_cache.get_alias_map(self.db)
            parser_rules = await parser_rule_cache.get_parser_rules(self.db)
            if detail_override is None:
                detail = await DetailQueryParser.parse_async(
                    user_text=text,
                    nlu_data={"workflow": "catalog"},
                    alias_map=alias_map,
                    parser_rules=parser_rules,
                )
                llm_call_count = 1
            else:
                detail = detail_override
                llm_call_count = max(0, int(llm_call_count_override or 0))

            conversation_state_enabled = bool(capabilities.chat_conversation_state_enabled)
            state_working: Optional[Dict[str, Any]] = None
            conversation_state_filter_merge_applied = False
            if conversation_state_enabled:
                state_working = await self._load_conversation_state(conversation_id=conversation_id)
            conversation_memory = conversation_state.load_memory_state(state_working)
            conversation_continuation = conversation_state.load_continuation_state(state_working)
            catalog_pagination_requested = bool(client_action_norm == "catalog_pagination")
            catalog_pagination_stale_requested = False
            catalog_pagination_offset = int(conversation_continuation.last_display_offset or 0)
            catalog_pagination_state_offset = int(conversation_continuation.last_display_offset or 0)
            catalog_pagination_limit = int(conversation_continuation.last_display_limit or product_presentation.PRODUCT_DISPLAY_LIMIT)
            catalog_pagination_query_key = str(conversation_continuation.last_query_cache_key or "")
            catalog_pagination_query_ids = list(conversation_continuation.last_query_product_ids or [])
            payload_query_key = str(client_action_payload.get("query_cache_key") or "").strip()
            payload_query_ids = [
                str(item).strip()
                for item in list(client_action_payload.get("query_product_ids") or [])
                if str(item).strip()
            ]
            try:
                payload_offset = int(client_action_payload.get("display_offset"))
            except Exception:
                payload_offset = None
            try:
                payload_limit = int(client_action_payload.get("display_limit"))
            except Exception:
                payload_limit = None

            if payload_query_key:
                catalog_pagination_query_key = payload_query_key
            if payload_query_ids:
                catalog_pagination_query_ids = list(payload_query_ids)
            if payload_offset is not None and payload_offset >= 0:
                if catalog_pagination_requested and payload_offset < catalog_pagination_state_offset:
                    catalog_pagination_stale_requested = True
                else:
                    catalog_pagination_offset = payload_offset
            if payload_limit is not None and payload_limit > 0:
                catalog_pagination_limit = payload_limit

            sku_tokens = routing_policy.extract_sku_tokens(text)
            unique_sku_tokens = [token for token in dict.fromkeys([str(item).strip() for item in sku_tokens]) if token]

            if conversation_state_enabled and state_working is not None and not catalog_pagination_requested:
                debug_state_version = int(conversation_memory.version or conversation_state.CONVERSATION_STATE_VERSION)
                tone_recent = reply_tone.normalize_recent(conversation_memory.tone_recent)
            else:
                debug_state_version = conversation_state.CONVERSATION_STATE_VERSION
                tone_recent = []
            route_decision = route_decision_override
            if route_decision is None:
                route_decision = routing_policy.WorkflowDecision(
                    workflow="fallback",
                    source=ComponentSource.ERROR,
                    needs_products=False,
                    needs_knowledge=False,
                    needs_clarification=True,
                    store_overview_request=False,
                    reason="missing_workflow_override",
                    confidence=0.0,
                )

            if catalog_pagination_requested:
                route_decision = replace(
                    route_decision,
                    workflow="catalog",
                    source=ComponentSource.SQL,
                    needs_products=True,
                    needs_knowledge=False,
                    needs_clarification=False,
                    store_overview_request=False,
                    knowledge_query="",
                    reason="catalog_pagination_continuation",
                    confidence=max(float(route_decision.confidence or 0.0), 0.9),
                )

            workflow = route_decision.workflow
            internal_workflow = str(internal_workflow_override or getattr(decision_state_override, "internal_workflow", "") or workflow)
            execution_state = PipelineExecutionState(
                debug_meta={
                    "component_pipeline_enabled": True,
                    "component_workflow": workflow,
                    "internal_workflow": internal_workflow,
                    "workflow_needs_products": bool(route_decision.needs_products),
                    "workflow_needs_knowledge": bool(route_decision.needs_knowledge),
                    "workflow_needs_clarification": bool(route_decision.needs_clarification),
                    "path_kind": "component_pipeline",
                    "route_override_used": bool(route_decision_override is not None),
                    "routing_selection_source": str(routing_selection_source or "component_pipeline"),
                    "store_overview_request": bool(route_decision.store_overview_request),
                    "conversation_state_enabled": conversation_state_enabled,
                    "conversation_state_filter_merge_applied": bool(conversation_state_filter_merge_applied),
                    "conversation_state_loaded_version": int(debug_state_version),
                    "conversation_state_written": False,
                    "detail_requested_fields": list(detail.requested_fields or []),
                    "intent_confidence": float(getattr(decision_state_override, "intent_confidence", 0.0) or 0.0),
                    "decision_answerability": str(getattr(decision_state_override, "answerability", "none") or "none"),
                },
                spans={
                    "workflow_routing_ms": 0.0,
                    "db_product_lookup_ms": 0.0,
                    "vector_search_ms": 0.0,
                    "llm_answer_ms": 0.0,
                    "response_build_ms": 0.0,
                },
                external_call_counts={},
            )
            execution_state.debug_meta["detail_extraction_mode"] = "llm"
            if str(route_decision.knowledge_query or "").strip():
                execution_state.debug_meta["knowledge_query_from_router"] = str(route_decision.knowledge_query or "").strip()
            if llm_call_count > 0:
                execution_state.external_call_counts["llm_detail_extraction"] = llm_call_count
            tone_controller = PipelineToneController(
                recent=list(tone_recent or []),
            )
            tone_debug = {
                "tone_humanizer_enabled": bool(capabilities.chat_tone_humanizer_enabled),
                "tone_channel_allowed": bool(capabilities.is_tone_channel_allowed(channel=channel)),
                "tone_active": bool(capabilities.chat_tone_humanizer_enabled and capabilities.is_tone_channel_allowed(channel=channel)),
            }
            execution_state.debug_meta.update(tone_debug)

            return PipelineRunSetup(
                normalized_text=normalized_text,
                detail=detail,
                conversation_state_enabled=conversation_state_enabled,
                state_working=state_working,
                catalog_pagination_requested=catalog_pagination_requested,
                catalog_pagination_stale_requested=catalog_pagination_stale_requested,
                catalog_pagination_offset=catalog_pagination_offset,
                catalog_pagination_state_offset=catalog_pagination_state_offset,
                catalog_pagination_limit=catalog_pagination_limit,
                catalog_pagination_query_key=catalog_pagination_query_key,
                catalog_pagination_query_ids=catalog_pagination_query_ids,
                sku_tokens=list(sku_tokens),
                unique_sku_tokens=list(unique_sku_tokens),
                route_decision=route_decision,
                workflow=workflow,
                store_overview_request=bool(route_decision.store_overview_request),
                knowledge_workflow=workflow == "knowledge",
                fallback_workflow=workflow == "fallback",
                source=route_decision.source,
                execution_state=execution_state,
                tone_controller=tone_controller,
                runtime_capabilities=capabilities,
                llm_call_count=llm_call_count,
                internal_workflow=internal_workflow,
                decision_state=decision_state_override,
            )
