from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.services.chat.harness.context import ChatHarnessContext, ChatHarnessDependencies


@dataclass(frozen=True)
class HarnessUnderstandingResult:
    user: Any
    conversation: Any
    understanding: Any
    detail: Any
    detail_llm_calls: int
    sku_tokens: list[str]
    alias_map: dict[str, dict[str, str]]
    parser_rules: Any
    existing_attribute_filters: dict[str, str]
    searchable_attribute_names: list[str]
    searchable_attribute_metadata: list[dict[str, Any]]


async def run_understanding(
    *,
    context: ChatHarnessContext,
    dependencies: ChatHarnessDependencies,
) -> HarnessUnderstandingResult:
    service = context.service
    request = context.request
    debug_meta = context.debug_meta
    text = context.user_text

    user = await service.get_or_create_user(request.user_id, request.customer_name, request.email)
    conversation = await service.get_or_create_conversation(user, request.conversation_id)
    context.conversation_id_value = dependencies.safe_conversation_id(
        conversation,
        context.conversation_id_value,
    )
    if context.conversation_id_value:
        context.trace.conversation_id = str(context.conversation_id_value)

    alias_map: dict[str, dict[str, str]] = {}
    parser_rules = dependencies.parser_rule_cache.get_cached_parser_rules()
    if hasattr(service.db, "execute"):
        try:
            alias_map = await dependencies.alias_cache.get_alias_map(service.db)
        except Exception as alias_exc:
            debug_meta["alias_cache_error"] = str(alias_exc)
        try:
            parser_rules = await dependencies.parser_rule_cache.get_parser_rules(service.db)
        except Exception as parser_exc:
            debug_meta["parser_rule_cache_error"] = str(parser_exc)

    sku_tokens = dependencies.routing_policy.extract_sku_tokens(text)
    existing_attribute_filters: dict[str, str] = {}
    if context.capabilities.chat_conversation_state_enabled and context.conversation_id_value:
        try:
            loaded_state = await service.get_conversation_state(context.conversation_id_value)
            existing_attribute_filters = dict(
                dependencies.conversation_state.load_memory_state(loaded_state).last_attribute_filters or {}
            )
            if existing_attribute_filters:
                debug_meta["conversation_existing_attribute_filters"] = dict(existing_attribute_filters)
        except Exception as state_exc:
            debug_meta["conversation_existing_attribute_filter_error"] = str(state_exc)

    searchable_attribute_names: list[str] = []
    searchable_attribute_metadata: list[dict[str, Any]] = []
    if hasattr(service.db, "execute"):
        try:
            searchable_attribute_metadata = await dependencies.eav_service.get_searchable_attribute_metadata(
                service.db
            )
            searchable_attribute_names = [
                str(item.get("name") or "").strip()
                for item in searchable_attribute_metadata
                if str(item.get("name") or "").strip()
            ]
            debug_meta["catalog_searchable_attribute_names"] = list(searchable_attribute_names)
            debug_meta["catalog_searchable_attribute_metadata"] = list(searchable_attribute_metadata)
        except Exception as attr_exc:
            debug_meta["catalog_searchable_attribute_error"] = str(attr_exc)

    context.trace.set_timing(
        "prepare_context",
        (time.perf_counter() - context.step_started) * 1000.0,
    )
    context.current_step = "understand"
    context.step_started = time.perf_counter()

    understanding = await dependencies.build_understanding_result(
        user_text=text,
        locale=str(request.locale or ""),
        channel=context.channel,
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
        detail_inference = await dependencies.infer_detail_query(
            user_text=text,
            workflow="catalog",
            alias_map=alias_map,
            parser_rules=parser_rules,
            existing_filters=existing_attribute_filters,
            db=service.db,
            searchable_attribute_names=searchable_attribute_names,
            searchable_attribute_metadata=searchable_attribute_metadata,
        )
        detail = dependencies.DetailQueryParser.build_from_inference(
            inference=detail_inference,
            parser_rules=parser_rules,
            searchable_attribute_names=searchable_attribute_names,
        )
        if dependencies.should_demote_attribute_detail_to_browse(
            user_text=text,
            requested_fields=detail.requested_fields,
            wants_image=detail.wants_image,
            sku_tokens=sku_tokens,
        ):
            detail = dependencies.DetailQuery(
                requested_fields=[],
                attribute_filters=dict(detail.attribute_filters or {}),
                wants_image=False,
                is_detail_request=False,
                semantic_hints=list(detail.semantic_hints or []),
                unknown_terms=list(getattr(detail, "unknown_terms", []) or []),
                clarify_focus=str(detail.clarify_focus or ""),
                parse_failed=bool(getattr(detail, "parse_failed", False)),
                parse_error=str(getattr(detail, "parse_error", "") or ""),
                extraction_debug=dict(getattr(detail, "extraction_debug", {}) or {}),
            )
            debug_meta["llm_detail_query_demoted_to_browse"] = True
        if (
            has_product_detail_signal
            and not detail.is_detail_request
            and not dependencies.is_browse_like_product_request(user_text=text, sku_tokens=sku_tokens)
        ):
            detail = dependencies.DetailQuery(
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
        detail = dependencies.DetailQuery(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            is_detail_request=False,
            semantic_hints=[],
            unknown_terms=[],
            clarify_focus="",
        )
        detail_llm_calls = 0

    context.trace.intent = str(understanding.intent or "") or context.trace.intent
    context.trace.workflow = str(understanding.workflow_hypothesis or "") or context.trace.workflow
    context.trace.set_timing(
        "understand",
        (time.perf_counter() - context.step_started) * 1000.0,
    )

    return HarnessUnderstandingResult(
        user=user,
        conversation=conversation,
        understanding=understanding,
        detail=detail,
        detail_llm_calls=detail_llm_calls,
        sku_tokens=list(sku_tokens or []),
        alias_map=alias_map,
        parser_rules=parser_rules,
        existing_attribute_filters=existing_attribute_filters,
        searchable_attribute_names=searchable_attribute_names,
        searchable_attribute_metadata=searchable_attribute_metadata,
    )

