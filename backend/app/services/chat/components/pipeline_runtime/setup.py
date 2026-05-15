from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings
from app.services.chat.components.pipeline_runtime.state import PipelineExecutionState
from app.services.chat.components.types import ComponentSource
from app.services.chat.parsing import parser_rule_cache
from app.services.chat.parsing.detail_query_parser import DetailQueryParser
from app.services.chat.parsing.llm_attribute_extractor import enrich_product_attribute_filters
from app.services.chat.parsing.attribute_resolver import resolve_catalog_attributes
from app.services.chat.parsing.query_understanding import infer_catalog_query_understanding
from app.services.catalog.attributes_service import eav_service
from app.services.chat.presentation import reply_tone
from app.services.chat.presentation import product_presentation
from app.services.chat.routing import routing_policy
from app.services.chat.routing import signals as routing_signals
from app.services.chat.routing.contracts import DecisionState
from app.services.chat.runtime.capabilities import ChatRuntimeCapabilities, build_chat_runtime_capabilities
from app.services.chat.runtime import alias_cache, clarification_state, context_resolver, conversation_state
from app.services.chat.runtime.search_plan import SearchPlan, build_search_plan
from app.services.chat.text_normalization import normalize_user_text

_OPAL_COLOR_PATTERN = r"\bopal\s+color\b"


def _merge_catalog_filter_hints(
    *,
    current_filters: Dict[str, str],
    user_text: str,
) -> tuple[Dict[str, str], bool]:
    merged = dict(current_filters or {})
    normalized = normalize_user_text(user_text)
    if "opal_color" in merged:
        return merged, False
    if not normalized:
        return merged, False
    if not re.search(_OPAL_COLOR_PATTERN, normalized):
        return merged, False
    merged["opal_color"] = "opal"
    return merged, True


def _pending_task_is_filled_by_current_turn(
    *,
    pending_task: Dict[str, Any],
    decision_state: Optional[DecisionState],
    product_anchor_present: bool,
) -> bool:
    task = dict(pending_task or {})
    missing_slot = str(task.get("missing_slot") or "").strip().lower()
    if missing_slot != "product_anchor":
        return False
    return bool(product_anchor_present)


def _pending_task_should_clear_for_topic_change(
    *,
    pending_task: Dict[str, Any],
    decision_state: Optional[DecisionState],
    route_decision: routing_policy.WorkflowDecision,
) -> bool:
    if not dict(pending_task or {}):
        return False
    intent = str(getattr(decision_state, "intent", "") or "").strip().lower()
    if intent in {"off_topic", "general_talking"}:
        return True
    if str(route_decision.workflow or "").strip().lower() == "knowledge":
        return True
    return False


def _has_product_anchor(
    *,
    text: str,
    detail: Any,
    sku_tokens: Sequence[str],
    contextual_filters_applied: bool,
) -> bool:
    if list(sku_tokens or []):
        return True
    if bool(contextual_filters_applied):
        return True

    if bool(getattr(detail, "is_detail_request", False)):
        return True
    if dict(getattr(detail, "attribute_filters", {}) or {}):
        return True
    if bool(getattr(detail, "wants_image", False)):
        return True

    normalized = normalize_user_text(text)
    if not normalized:
        return False
    return bool(
        routing_signals.has_specific_product_hint_signal(normalized)
        or routing_signals.has_explicit_product_browse_signal(normalized)
        or routing_signals.looks_like_product_search(normalized)
    )


def _merge_filter_maps(*, base: Dict[str, str], incoming: Dict[str, str]) -> Dict[str, str]:
    merged = dict(base or {})
    for key, value in dict(incoming or {}).items():
        clean_key = str(key or "").strip().lower()
        clean_value = str(value or "").strip()
        if not clean_key or not clean_value:
            continue
        if clean_key == "category" and merged.get(clean_key):
            existing = [item for item in str(merged[clean_key]).split(";;") if item.strip()]
            new_items = [item for item in clean_value.split(";;") if item.strip()]
            merged[clean_key] = ";;".join(list(dict.fromkeys(existing + new_items)))
        else:
            merged[clean_key] = clean_value
    return merged


def _replace_detail(detail: Any, **changes: Any) -> Any:
    try:
        return replace(detail, **changes)
    except TypeError:
        for key, value in changes.items():
            try:
                setattr(detail, key, value)
            except Exception:
                continue
        return detail


def _merge_semantic_hints(*, existing: Sequence[Any], incoming: Sequence[Any]) -> List[str]:
    hints: List[str] = []
    seen: set[str] = set()
    for raw in list(existing or []) + list(incoming or []):
        text = normalize_user_text(str(raw or ""))
        if not text or text in seen:
            continue
        seen.add(text)
        hints.append(text)
    return hints


def _internal_workflow_from_query_intent(intent: str) -> str:
    intent_norm = str(intent or "").strip().lower()
    if intent_norm == "product_detail":
        return "product_detail"
    if intent_norm == "compare_products":
        return "compare_products"
    if intent_norm == "store_overview":
        return "company_info"
    if intent_norm == "knowledge":
        return "policy_info"
    return "catalog_search"


def _price_or_stock_fields_from_text(text: str) -> List[str]:
    normalized = normalize_user_text(text)
    fields: List[str] = []
    if any(term in normalized for term in ("price", "cost", "how much", "cheaper", "cheapest")):
        fields.append("price")
    if any(term in normalized for term in ("stock", "available", "availability", "in stock")):
        fields.append("stock")
    return fields


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
    search_plan: SearchPlan
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
            searchable_attribute_names: List[str] = []
            searchable_attribute_metadata: List[Dict[str, Any]] = []
            if hasattr(self.db, "execute"):
                try:
                    searchable_attribute_metadata = await eav_service.get_searchable_attribute_metadata(self.db)
                    searchable_attribute_names = [
                        str(item.get("name") or "").strip()
                        for item in searchable_attribute_metadata
                        if str(item.get("name") or "").strip()
                    ]
                except Exception:
                    searchable_attribute_names = []
                    searchable_attribute_metadata = []
            if detail_override is None:
                detail = await DetailQueryParser.parse_async(
                    user_text=text,
                    nlu_data={"workflow": "catalog"},
                    alias_map=alias_map,
                    parser_rules=parser_rules,
                    db=self.db,
                    searchable_attribute_names=searchable_attribute_names,
                    searchable_attribute_metadata=searchable_attribute_metadata,
                )
                llm_call_count = 1
            else:
                detail = detail_override
                llm_call_count = max(0, int(llm_call_count_override or 0))

            conversation_state_enabled = bool(capabilities.chat_conversation_state_enabled)
            state_working: Optional[Dict[str, Any]] = None
            if conversation_state_enabled:
                state_working = await self._load_conversation_state(conversation_id=conversation_id)
            conversation_memory = conversation_state.load_memory_state(state_working)
            conversation_continuation = conversation_state.load_continuation_state(state_working)
            pending_task = conversation_state.load_pending_task(state_working)
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

            context_result = context_resolver.resolve_context(
                user_message=text,
                conversation_id=conversation_id,
                loaded_state=state_working,
                workflow=str(route_decision.workflow or ""),
                extracted_filters=dict(getattr(detail, "attribute_filters", {}) or {}),
                requested_fields=list(getattr(detail, "requested_fields", []) or []),
                semantic_hints=list(getattr(detail, "semantic_hints", []) or []),
                is_detail_request=bool(getattr(detail, "is_detail_request", False)),
                sku_tokens=unique_sku_tokens,
                client_action=client_action_norm,
                client_action_payload=client_action_payload,
                decision_state=decision_state_override,
                normalized_text=normalized_text,
            )
            context_debug = context_result.to_debug_dict()
            contextual_filters_applied = False
            contextual_filter_reason = ""
            contextual_strictness: Dict[str, str] = {}
            catalog_pagination_requested = False
            catalog_pagination_stale_requested = False
            if context_result.context_type == "pagination" and context_result.pagination_action and context_result.safe_to_retrieve:
                pagination_action = dict(context_result.pagination_action or {})
                catalog_pagination_requested = True
                catalog_pagination_query_key = str(pagination_action.get("query_cache_key") or catalog_pagination_query_key)
                action_ids = [
                    str(item).strip()
                    for item in list(pagination_action.get("query_product_ids") or [])
                    if str(item).strip()
                ]
                if action_ids:
                    catalog_pagination_query_ids = list(action_ids)
                catalog_pagination_offset = int(pagination_action.get("display_offset") or catalog_pagination_offset)
                catalog_pagination_limit = int(pagination_action.get("display_limit") or catalog_pagination_limit)
            elif context_result.context_type == "pagination" and context_result.should_clarify:
                catalog_pagination_stale_requested = bool(context_result.clarification_reason == "pagination_stale")
            if context_result.resolved_filters and context_result.context_action in {"reuse", "update", "reset"}:
                current_filters = dict(getattr(detail, "attribute_filters", {}) or {})
                if dict(context_result.resolved_filters or {}) != current_filters:
                    detail = _replace_detail(detail, attribute_filters=dict(context_result.resolved_filters or {}))
                    contextual_filters_applied = bool(context_result.context_used and context_result.confidence >= context_resolver.CONTEXT_USE_THRESHOLD)
                    contextual_filter_reason = str(context_result.reason or context_result.context_action)
            if context_result.context_type == "filter_refinement" and context_result.safe_to_retrieve:
                for key in dict(context_result.debug.get("current_filters") or {}).keys():
                    clean_key = str(key or "").strip().lower()
                    if clean_key:
                        contextual_strictness[clean_key] = "required"
            if context_result.active_product and context_result.confidence >= context_resolver.CONTEXT_USE_THRESHOLD:
                active_product = dict(context_result.active_product or {})
                active_sku = str(active_product.get("sku") or active_product.get("master_code") or "").strip()
                if active_sku and active_sku not in unique_sku_tokens:
                    unique_sku_tokens.append(active_sku)
                requested_fields = list(getattr(detail, "requested_fields", []) or [])
                requested_fields = list(dict.fromkeys(requested_fields + _price_or_stock_fields_from_text(text)))
                if context_result.resolved_intent == "product_detail" and "attributes" not in requested_fields:
                    requested_fields.append("attributes")
                if context_result.resolved_intent in {"product_detail", "inventory_check"}:
                    detail = _replace_detail(
                        detail,
                        requested_fields=requested_fields,
                        is_detail_request=True,
                    )

            product_anchor_present = _has_product_anchor(
                text=text,
                detail=detail,
                sku_tokens=unique_sku_tokens,
                contextual_filters_applied=bool(
                    contextual_filters_applied
                    or context_result.active_product
                    or context_result.bypass_missing_anchor_clarify
                    or list(context_result.resolved_product_anchor_ids or [])
                    or list(context_result.resolved_product_anchor_skus or [])
                ),
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
            if (
                route_decision.workflow == "knowledge"
                and bool(getattr(decision_state_override, "needs_knowledge", False))
                and dict(getattr(detail, "attribute_filters", {}) or {})
                and "product_anchor" in str(getattr(decision_state_override, "missing_slot", "") or "").strip().lower()
            ):
                route_decision = replace(
                    route_decision,
                    workflow="catalog",
                    source=ComponentSource.SQL,
                    needs_products=True,
                    needs_knowledge=True,
                    needs_clarification=False,
                    store_overview_request=False,
                    reason="mixed_product_knowledge_detail_override",
                    confidence=max(float(route_decision.confidence or 0.0), 0.8),
                )
            pending_task_resume: Dict[str, Any] = {}
            pending_task_cleared = False
            pending_task_advanced = False
            if conversation_state_enabled and state_working is not None and pending_task:
                if bool(context_result.resume_pending_task):
                    pending_task_resume = dict(pending_task)
                    state_working = conversation_state.clear_pending_task(state_working)
                    pending_task_cleared = True
                    if route_decision.workflow != "catalog":
                        route_decision = replace(
                            route_decision,
                            workflow="catalog",
                            source=ComponentSource.SQL,
                            needs_products=True,
                            needs_knowledge=False,
                            needs_clarification=False,
                            store_overview_request=False,
                            knowledge_query="",
                            reason="pending_task_resumed",
                            confidence=max(float(route_decision.confidence or 0.0), 0.8),
                        )
                elif (
                    context_result.context_type in {"detail_reference", "explicit_sku"}
                    and _pending_task_is_filled_by_current_turn(
                    pending_task=pending_task,
                    decision_state=decision_state_override,
                    product_anchor_present=product_anchor_present,
                    )
                ):
                    pending_task_resume = dict(pending_task)
                    state_working = conversation_state.clear_pending_task(state_working)
                    pending_task_cleared = True
                    if route_decision.workflow != "catalog":
                        route_decision = replace(
                            route_decision,
                            workflow="catalog",
                            source=ComponentSource.SQL,
                            needs_products=True,
                            needs_knowledge=False,
                            needs_clarification=False,
                            store_overview_request=False,
                            knowledge_query="",
                            reason="pending_task_resumed",
                            confidence=max(float(route_decision.confidence or 0.0), 0.8),
                        )
                elif _pending_task_should_clear_for_topic_change(
                    pending_task=pending_task,
                    decision_state=decision_state_override,
                    route_decision=route_decision,
                ):
                    state_working = conversation_state.clear_pending_task(state_working)
                    pending_task_cleared = True
                else:
                    state_working = conversation_state.advance_pending_task_turn(state_working)
                    pending_task_advanced = True

            query_understanding_debug: Dict[str, Any] = {}
            query_understanding_llm_calls = 0
            query_understanding_strictness: Dict[str, str] = {}
            query_understanding_unresolved: List[Dict[str, str]] = []
            query_understanding_semantic_query = ""
            query_understanding_uses_context = False
            query_understanding_anchor_required = False
            query_understanding_internal_workflow = ""
            if bool(getattr(settings, "CHAT_QUERY_UNDERSTANDING_V2_ENABLED", False)):
                prior_search_plan = {
                    "last_attribute_filters": dict(conversation_memory.last_attribute_filters or {}),
                    "last_route": str(conversation_memory.last_route or ""),
                    "last_refined_query": str(conversation_memory.last_refined_query or ""),
                }
                pagination_state = {
                    "query_cache_key": str(conversation_continuation.last_query_cache_key or ""),
                    "query_product_ids": list(conversation_continuation.last_query_product_ids or []),
                    "result_count": int(conversation_continuation.last_result_count or 0),
                    "display_offset": int(conversation_continuation.last_display_offset or 0),
                    "display_limit": int(conversation_continuation.last_display_limit or 0),
                }
                recent_context = {
                    "last_attribute_filters": dict(conversation_memory.last_attribute_filters or {}),
                    "last_requested_fields": list(conversation_memory.last_requested_fields or []),
                    "last_product_ids": list(conversation_memory.last_product_ids or []),
                    "last_product_skus": list(conversation_memory.last_product_skus or []),
                    "active_product": dict(conversation_memory.active_product or {}),
                    "displayed_products": list(conversation_memory.displayed_products or []),
                    "pending_task": dict(pending_task_resume or pending_task or {}),
                }
                query_understanding = await infer_catalog_query_understanding(
                    user_text=text,
                    normalized_text=normalized_text,
                    recent_context=recent_context,
                    previous_product_ids=list(conversation_memory.last_product_ids or []),
                    previous_search_plan=prior_search_plan,
                    pagination_state=pagination_state,
                    known_catalog_attributes=list(searchable_attribute_metadata or []),
                    sku_tokens=unique_sku_tokens,
                )
                query_understanding_debug.update(dict(query_understanding.debug or {}))
                query_understanding_llm_calls += int(query_understanding.llm_call_count or 0)
                understanding = query_understanding.understanding
                if query_understanding.valid and query_understanding.trusted and understanding is not None:
                    query_understanding_semantic_query = str(understanding.semantic_query or "").strip()
                    query_understanding_uses_context = bool(understanding.uses_previous_context)
                    query_understanding_anchor_required = bool(understanding.product_anchor_required)
                    resolved_plan = await resolve_catalog_attributes(
                        db=self.db,
                        understanding=understanding,
                    )
                    query_understanding_debug["resolved_attributes"] = dict(resolved_plan.resolved_hard_constraints)
                    query_understanding_debug["unresolved_attributes"] = list(resolved_plan.unresolved_constraints)
                    query_understanding_debug["attribute_resolution"] = resolved_plan.to_debug_dict()
                    query_understanding_strictness = dict(resolved_plan.strictness or {})
                    query_understanding_unresolved = list(resolved_plan.unresolved_constraints or [])

                    base_filters = dict(getattr(detail, "attribute_filters", {}) or {})
                    if understanding.uses_previous_context:
                        base_filters = _merge_filter_maps(
                            base=dict(conversation_memory.last_attribute_filters or {}),
                            incoming=base_filters,
                        )
                    merged_filters = _merge_filter_maps(
                        base=base_filters,
                        incoming=dict(resolved_plan.resolved_hard_constraints or {}),
                    )
                    merged_hints = _merge_semantic_hints(
                        existing=list(getattr(detail, "semantic_hints", []) or []),
                        incoming=list(resolved_plan.resolved_soft_hints or []),
                    )
                    requested_fields = list(getattr(detail, "requested_fields", []) or [])
                    if understanding.intent == "product_detail":
                        requested_fields = list(dict.fromkeys(requested_fields + _price_or_stock_fields_from_text(text)))
                    detail = _replace_detail(
                        detail,
                        attribute_filters=merged_filters,
                        semantic_hints=merged_hints,
                        requested_fields=requested_fields,
                        is_detail_request=bool(getattr(detail, "is_detail_request", False) or requested_fields or understanding.intent == "product_detail"),
                    )

                    if understanding.intent in {"catalog_search", "product_detail", "compare_products", "attribute_list"} and understanding.is_searchable_enough:
                        route_decision = replace(
                            route_decision,
                            workflow="catalog",
                            source=ComponentSource.SQL,
                            needs_products=True,
                            needs_clarification=False,
                            store_overview_request=False,
                            reason="query_understanding_searchable",
                            confidence=max(float(route_decision.confidence or 0.0), float(understanding.confidence.intent or 0.0)),
                        )
                        query_understanding_internal_workflow = _internal_workflow_from_query_intent(understanding.intent)

                    missing_slots = list(understanding.missing_slots or [])
                    if query_understanding_unresolved:
                        missing_slots.extend(
                            str(item.get("attribute") or "")
                            for item in query_understanding_unresolved
                            if str(item.get("attribute") or "").strip()
                        )
                    task_id = clarification_state.build_task_id(
                        intent=understanding.intent,
                        missing_slots=missing_slots,
                        semantic_query=query_understanding_semantic_query or text,
                        hard_constraints=dict(resolved_plan.resolved_hard_constraints or {}),
                    )
                    loaded_clarification_state = conversation_state.load_clarification_state(state_working)
                    loop_count = clarification_state.current_count(
                        loaded_clarification_state,
                        task_id=task_id,
                    )
                    query_understanding_debug["clarification_task_id"] = task_id
                    query_understanding_debug["clarification_loop_count"] = loop_count
                    query_understanding_debug["clarification_loop_stop"] = clarification_state.should_stop_clarifying(
                        loaded_clarification_state,
                        task_id=task_id,
                    )
                    query_understanding_debug["query_understanding_detail_filters"] = dict(getattr(detail, "attribute_filters", {}) or {})
                    query_understanding_debug["query_understanding_semantic_hints"] = list(getattr(detail, "semantic_hints", []) or [])

            workflow = route_decision.workflow
            internal_workflow = str(
                query_understanding_internal_workflow
                or internal_workflow_override
                or getattr(decision_state_override, "internal_workflow", "")
                or workflow
            )
            effective_strictness = dict(contextual_strictness or {})
            effective_strictness.update(dict(query_understanding_strictness or {}))
            search_plan = build_search_plan(
                user_text=text,
                workflow=workflow,
                detail=detail,
                sku_tokens=unique_sku_tokens,
                knowledge_query=str(route_decision.knowledge_query or ""),
                conversation_anchor={
                    "last_attribute_filters": dict(conversation_memory.last_attribute_filters or {}),
                    "last_route": str(conversation_memory.last_route or ""),
                },
                context_allowed=bool(query_understanding_uses_context or contextual_filters_applied or context_result.context_used),
                context_reason=(
                    "query_understanding_previous_context"
                    if query_understanding_uses_context
                    else (contextual_filter_reason or str(context_result.reason or ""))
                ),
                strictness=effective_strictness,
                unresolved_constraints=query_understanding_unresolved,
                semantic_query=query_understanding_semantic_query,
                uses_previous_context=query_understanding_uses_context,
                product_anchor_required=query_understanding_anchor_required,
            )
            execution_state = PipelineExecutionState(
                debug_meta={
                    "component_pipeline_enabled": True,
                    "component_workflow": workflow,
                    "internal_workflow": internal_workflow,
                    "response_intent": str(getattr(decision_state_override, "intent", "") or ""),
                    "response_subintent": str(getattr(decision_state_override, "subintent", "") or ""),
                    "response_policy": str(getattr(decision_state_override, "response_policy", "") or ""),
                    "response_user_goal": str(getattr(decision_state_override, "user_goal", "") or ""),
                    "response_product_query": str(getattr(decision_state_override, "product_query", "") or ""),
                    "response_clarify_question": str(getattr(decision_state_override, "clarify_question", "") or ""),
                    "response_pending_task_type": str(getattr(decision_state_override, "pending_task_type", "") or ""),
                    "response_missing_slot": str(getattr(decision_state_override, "missing_slot", "") or ""),
                    "workflow_needs_products": bool(route_decision.needs_products),
                    "workflow_needs_knowledge": bool(route_decision.needs_knowledge),
                    "workflow_needs_clarification": bool(route_decision.needs_clarification),
                    "path_kind": "component_pipeline",
                    "route_override_used": bool(route_decision_override is not None),
                    "routing_selection_source": str(routing_selection_source or "component_pipeline"),
                    "store_overview_request": bool(route_decision.store_overview_request),
                    "conversation_state_enabled": conversation_state_enabled,
                    "conversation_state_loaded_version": int(debug_state_version),
                    "conversation_state_written": False,
                    "conversation_state_filter_merge_applied": bool(contextual_filters_applied),
                    "conversation_state_filter_merge_reason": str(contextual_filter_reason or ""),
                    "context_resolver_used": True,
                    "context_resolution": context_debug,
                    "context_type": str(context_result.context_type or "none"),
                    "uses_previous_context": bool(context_result.uses_previous_context),
                    "context_used": bool(context_result.context_used),
                    "context_action": str(context_result.context_action or ""),
                    "context_confidence": float(context_result.confidence or 0.0),
                    "context_reason": str(context_result.reason or ""),
                    "context_reset_reason": str(context_result.reset_reason or ""),
                    "context_resolved_intent": str(context_result.resolved_intent or ""),
                    "context_merged_query": str(context_result.merged_query or ""),
                    "merged_attribute_filters": dict(context_result.merged_attribute_filters or {}),
                    "context_resolved_product_anchor_ids": list(context_result.resolved_product_anchor_ids or []),
                    "context_resolved_product_anchor_skus": list(context_result.resolved_product_anchor_skus or []),
                    "context_selected_product_index": context_result.selected_product_index,
                    "context_selected_product_indices": list(context_result.selected_product_indices or []),
                    "resume_pending_task": bool(context_result.resume_pending_task),
                    "bypass_missing_anchor_clarify": bool(context_result.bypass_missing_anchor_clarify),
                    "safe_to_retrieve": bool(context_result.safe_to_retrieve),
                    "context_should_clarify": bool(context_result.should_clarify),
                    "context_clarification_reason": str(context_result.clarification_reason or ""),
                    "context_active_product": dict(context_result.active_product or {}),
                    "context_referenced_products": [dict(item) for item in list(context_result.referenced_products or [])],
                    "context_pending_task_action": dict(context_result.pending_task_action or {}),
                    "context_requires_clarification": bool(context_result.should_clarify or context_result.context_action == "clarify"),
                    "pending_task_loaded": bool(pending_task),
                    "pending_task_resumed": bool(pending_task_resume),
                    "pending_task_cleared": bool(pending_task_cleared),
                    "pending_task_advanced": bool(pending_task_advanced),
                    "pending_task_type": str((pending_task_resume or pending_task).get("task_type") or ""),
                    "pending_task_missing_slot": str((pending_task_resume or pending_task).get("missing_slot") or ""),
                    "pending_task_original_question": str((pending_task_resume or pending_task).get("original_question") or ""),
                    "conversation_last_product_ids": list(conversation_memory.last_product_ids or []),
                    "conversation_last_product_skus": list(conversation_memory.last_product_skus or []),
                    "catalog_product_anchor_present": bool(product_anchor_present),
                    "detail_requested_fields": list(detail.requested_fields or []),
                    "detail_unknown_terms": list(getattr(detail, "unknown_terms", []) or []),
                    "detail_parse_failed": bool(getattr(detail, "parse_failed", False)),
                    "detail_parse_error": str(getattr(detail, "parse_error", "") or ""),
                    "intent_confidence": float(getattr(decision_state_override, "intent_confidence", 0.0) or 0.0),
                    "decision_answerability": str(getattr(decision_state_override, "answerability", "none") or "none"),
                    "search_plan": search_plan.to_debug_dict(),
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
            if query_understanding_debug:
                execution_state.debug_meta.update(query_understanding_debug)
                execution_state.debug_meta["search_plan"] = search_plan.to_debug_dict()
            if query_understanding_llm_calls > 0:
                execution_state.external_call_counts["llm_query_understanding"] = int(query_understanding_llm_calls)
            detail_debug = dict(getattr(detail, "extraction_debug", {}) or {})
            for key in (
                "llm_detail_query_error",
                "llm_detail_query_fallback_source",
                "llm_detail_query_fallback_filter",
                "llm_detail_query_confidence",
                "llm_detail_query_attribute_keys",
                "llm_detail_query_semantic_hints",
                "llm_detail_query_unknown_terms",
                "llm_detail_query_clarify_focus",
            ):
                if key in detail_debug:
                    execution_state.debug_meta[key] = detail_debug.get(key)
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
                search_plan=search_plan,
                llm_call_count=int(llm_call_count or 0) + int(query_understanding_llm_calls or 0),
                internal_workflow=internal_workflow,
                decision_state=decision_state_override,
            )
