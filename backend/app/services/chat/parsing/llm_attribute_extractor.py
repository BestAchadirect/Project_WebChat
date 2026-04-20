from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.prompts.ambiguity import AMBIGUITY_FAMILY_KEYS, normalize_focus_key
from app.models.product_attribute import AttributeDefinition, FacetValueAlias, ProductAttributeValue
from app.services.ai.llm_service import llm_service
from app.services.chat.parsing.attribute_normalization import (
    normalize_attribute_value,
    normalize_lexical_alias_map,
    normalize_text,
)
from app.services.chat.parsing.parser_rule_types import ParserRuleSet, empty_rule_set
from app.services.chat.parsing.search_policy import HARD_FILTER_KEYS
import app.services.chat.routing.routing_policy as routing_policy
from app.services.chat.routing.decision_engine import build_decision_state
from app.services.chat.routing.understanding import build_understanding_result
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.knowledge.retrieval import KnowledgeRetrievalService
from app.services.knowledge.tagging import build_knowledge_query_tags
from app.utils.synonym_rules import (
    ATTRIBUTE_LIST_TARGETS,
    DEFAULT_SOFT_ATTRIBUTE_KEYS,
    normalize_attribute_list_target,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AttributeExtractionResult:
    exact_filters: Dict[str, str]
    semantic_hints: List[str]
    soft_filters: Dict[str, str] = field(default_factory=dict)
    clarify_focus: str = ""
    confidence: float = 0.0
    llm_call_count: int = 0
    debug: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AttributeListTargetResult:
    target: str
    confidence: float = 0.0
    llm_call_count: int = 0
    debug: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetailQueryInferenceResult:
    requested_fields: List[str]
    attribute_filters: Dict[str, str]
    wants_image: bool
    semantic_hints: List[str]
    clarify_focus: str
    confidence: float = 0.0
    llm_call_count: int = 0
    debug: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SurfaceIntentClassificationResult:
    intent_family: str
    knowledge_query: str = ""
    reason: str = ""
    confidence: float = 0.0
    store_overview_request: bool = False
    llm_call_count: int = 0
    debug: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatInterpretationResult:
    execution_decision: routing_policy.ExecutionDecision
    detail: DetailQueryInferenceResult
    llm_call_count: int = 0
    debug: Dict[str, Any] = field(default_factory=dict)


def _allowed_exact_attributes(rule_set: ParserRuleSet | None) -> List[str]:
    active_rules = rule_set or empty_rule_set()
    declared = {
        str(item or "").strip().lower()
        for item in list(active_rules.allowed_attribute_filters or [])
        if str(item or "").strip()
    }
    if declared:
        return sorted(declared.intersection(HARD_FILTER_KEYS))
    return sorted(HARD_FILTER_KEYS)


def _allowed_soft_attributes(rule_set: ParserRuleSet | None) -> List[str]:
    active_rules = rule_set or empty_rule_set()
    declared = {
        str(item or "").strip().lower()
        for item in list(active_rules.allowed_attribute_filters or [])
        if str(item or "").strip()
    }
    if declared:
        return sorted(declared.difference(HARD_FILTER_KEYS))
    return sorted(DEFAULT_SOFT_ATTRIBUTE_KEYS)


def _normalize_candidate_filters(
    *,
    filters: Mapping[str, str] | None,
    alias_map: Mapping[str, Dict[str, str]] | None,
    allowed_attributes: Sequence[str],
) -> Dict[str, str]:
    allowed = {str(item or "").strip().lower() for item in list(allowed_attributes or []) if str(item or "").strip()}
    normalized_aliases = normalize_lexical_alias_map(dict(alias_map or {}))
    clean: Dict[str, str] = {}
    for raw_key, raw_value in dict(filters or {}).items():
        key = normalize_text(raw_key)
        if not key or (allowed and key not in allowed):
            continue
        value = normalize_attribute_value(
            key=key,
            value=raw_value,
            alias_map=normalized_aliases,
        )
        if value:
            clean[key] = value
    return clean


async def _value_exists_for_attribute(
    db: AsyncSession,
    *,
    attribute_name: str,
    normalized_value: str,
) -> bool:
    clean_attribute = normalize_text(attribute_name)
    clean_value = normalize_text(normalized_value)
    if not clean_attribute or not clean_value:
        return False

    attribute_stmt = (
        select(AttributeDefinition.id)
        .where(AttributeDefinition.is_enabled.is_(True))
        .where(func.lower(AttributeDefinition.name) == clean_attribute)
        .limit(1)
    )
    attribute_id = (await db.execute(attribute_stmt)).scalar_one_or_none()
    if attribute_id is None:
        return False

    alias_stmt = (
        select(FacetValueAlias.id)
        .where(FacetValueAlias.attribute_id == int(attribute_id))
        .where(FacetValueAlias.is_active.is_(True))
        .where(
            or_(
                func.lower(func.coalesce(FacetValueAlias.raw_value_norm, FacetValueAlias.raw_value, "")) == clean_value,
                func.lower(func.coalesce(FacetValueAlias.canonical_value_norm, FacetValueAlias.canonical_value, "")) == clean_value,
            )
        )
        .limit(1)
    )
    if (await db.execute(alias_stmt)).scalar_one_or_none() is not None:
        return True

    value_stmt = (
        select(ProductAttributeValue.id)
        .where(ProductAttributeValue.attribute_id == int(attribute_id))
        .where(func.lower(func.coalesce(ProductAttributeValue.value_norm, ProductAttributeValue.value, "")) == clean_value)
        .limit(1)
    )
    return (await db.execute(value_stmt)).scalar_one_or_none() is not None


async def _validate_attribute_filters(
    db: AsyncSession,
    *,
    filters: Mapping[str, str] | None,
    alias_map: Mapping[str, Dict[str, str]] | None,
    allowed_attributes: Sequence[str],
) -> Dict[str, str]:
    clean_filters = _normalize_candidate_filters(
        filters=filters,
        alias_map=alias_map,
        allowed_attributes=allowed_attributes,
    )
    if not clean_filters or not hasattr(db, "execute"):
        return {}

    validated: Dict[str, str] = {}
    for key, value in clean_filters.items():
        try:
            if await _value_exists_for_attribute(
                db,
                attribute_name=key,
                normalized_value=value,
            ):
                validated[key] = value
        except Exception:
            logger.exception("attribute validation failed for %s=%s", key, value)
    return validated


def _normalize_semantic_hints(raw_hints: Any) -> List[str]:
    hints: List[str] = []
    seen: set[str] = set()
    for raw in list(raw_hints or []):
        hint = normalize_text(str(raw or ""))
        if not hint or hint in seen:
            continue
        seen.add(hint)
        hints.append(hint)
        if len(hints) >= 4:
            break
    return hints


def _normalize_attribute_list_target(raw_target: Any) -> str:
    return normalize_attribute_list_target(raw_target)


def _normalize_requested_fields(raw_fields: Any) -> List[str]:
    if not isinstance(raw_fields, list):
        return []
    clean: List[str] = []
    seen: set[str] = set()
    for raw in raw_fields:
        field = normalize_text(str(raw or ""))
        if not field or field in seen:
            continue
            seen.add(field)
            clean.append(field)
    return clean


def _normalize_surface_intent_family(raw_family: Any) -> str:
    family = normalize_text(str(raw_family or ""))
    allowed = {"support_contact", "catalog", "knowledge_other", "off_topic", "unclear"}
    return family if family in allowed else "unclear"


def _surface_intent_relevance_threshold() -> float:
    return float(getattr(settings, "CHAT_KNOWLEDGE_MIN_RELEVANCE", 0.55))


def _build_surface_probe_queries(clean_text: str) -> List[str]:
    text = normalize_text(clean_text)
    if not text:
        return []
    queries = [text]
    if any(marker in text for marker in ("company", "about us", "about", "business", "store", "showroom", "location", "where")):
        queries.extend(
            [
                "where is your company located",
                "company location showroom about us",
                "contact company location showroom",
            ]
        )
    if any(marker in text for marker in ("contact", "support", "sales", "representative", "customer service", "phone", "email", "whatsapp")):
        queries.extend(
            [
                "how can i contact customer service",
                "contact support sales team",
                "sales representative customer service contact",
            ]
        )
    deduped: List[str] = []
    seen: set[str] = set()
    for query in queries:
        norm = normalize_text(query)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(norm)
    return deduped


async def _probe_surface_intent_with_vector_search(
    *,
    db: AsyncSession | None,
    user_text: str,
    store_overview_request: bool = False,
) -> SurfaceIntentClassificationResult:
    clean_text = normalize_text(user_text)
    debug: Dict[str, Any] = {
        "llm_chat_surface_intent_enabled": bool(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_ENABLED", True)),
        "llm_chat_surface_intent_used": False,
        "llm_chat_surface_intent_vector_used": False,
        "llm_chat_surface_intent_vector_relevance": 0.0,
        "llm_chat_surface_intent_family": "",
        "llm_chat_surface_intent_confidence": 0.0,
        "llm_chat_surface_intent_reason": "",
        "llm_chat_surface_intent_knowledge_query": "",
        "llm_chat_surface_intent_store_overview_request": False,
    }
    if not clean_text or db is None or not hasattr(db, "execute"):
        return SurfaceIntentClassificationResult(intent_family="unclear", debug=debug)

    try:
        probe_queries = _build_surface_probe_queries(clean_text)
        retrieval = KnowledgeRetrievalService(db)
        best_source = None
        best_query = ""
        best_relevance = 0.0
        for probe_query in probe_queries:
            embedding = await llm_service.generate_embedding(probe_query)
            sources = await retrieval.search(
                query_text=probe_query,
                query_embedding=embedding,
                limit=1,
                store_overview_request=store_overview_request or ("company" in probe_query or "about us" in probe_query or "location" in probe_query),
            )
            if not sources:
                continue
            top_source = sources[0]
            top_relevance = float(getattr(top_source, "relevance", 0.0) or 0.0)
            if best_source is not None and top_relevance <= best_relevance:
                continue
            best_source = top_source
            best_query = probe_query
            best_relevance = top_relevance

        if best_source is None:
            return SurfaceIntentClassificationResult(intent_family="unclear", debug=debug)

        debug["llm_chat_surface_intent_vector_used"] = True
        debug["llm_chat_surface_intent_vector_relevance"] = best_relevance
        debug["llm_chat_surface_intent_vector_title"] = str(getattr(best_source, "title", "") or "")
        debug["llm_chat_surface_intent_vector_category"] = str(getattr(best_source, "category", "") or "")
        debug["llm_chat_surface_intent_vector_summary"] = str(getattr(best_source, "summary", "") or "")
        debug["llm_chat_surface_intent_vector_snippet"] = str(getattr(best_source, "content_snippet", "") or "")

        threshold = _surface_intent_relevance_threshold()
        if best_relevance < threshold:
            return SurfaceIntentClassificationResult(intent_family="unclear", debug=debug)

        query_tags = build_knowledge_query_tags(clean_text)
        top_text = " ".join(
            part
            for part in (
                str(getattr(best_source, "title", "") or ""),
                str(getattr(best_source, "category", "") or ""),
                str(getattr(best_source, "summary", "") or ""),
                str(getattr(best_source, "content_snippet", "") or ""),
            )
            if part
        ).lower()
        contact_query_text = " ".join(
            part for part in (clean_text, best_query) if part
        ).lower()
        contactish = "contact" in query_tags or any(
            marker in contact_query_text
            for marker in (
                "contact",
                "customer service",
                "support",
                "sales person",
                "sales representative",
                "representative",
                "phone",
                "email",
                "whatsapp",
            )
        )
        store_overviewish = any(
            marker in top_text
            for marker in (
                "company",
                "about",
                "location",
                "showroom",
                "visit",
                "hours",
            )
        )
        if contactish:
            debug["llm_chat_surface_intent_family"] = "support_contact"
            debug["llm_chat_surface_intent_confidence"] = best_relevance
            debug["llm_chat_surface_intent_reason"] = "vector_knowledge_probe_contact"
            debug["llm_chat_surface_intent_knowledge_query"] = "how can i contact customer service"
            debug["llm_chat_surface_intent_store_overview_request"] = bool(store_overview_request)
            return SurfaceIntentClassificationResult(
                intent_family="support_contact",
                knowledge_query="how can i contact customer service",
                reason="vector_knowledge_probe_contact",
                confidence=best_relevance,
                store_overview_request=bool(store_overview_request),
                llm_call_count=0,
                debug=debug,
            )

        query_is_store_overview = bool(
            store_overview_request
            or "company" in best_query
            or "about us" in best_query
            or "location" in best_query
            or store_overviewish
        )
        debug["llm_chat_surface_intent_family"] = "knowledge_other"
        debug["llm_chat_surface_intent_confidence"] = best_relevance
        debug["llm_chat_surface_intent_reason"] = "vector_knowledge_probe"
        debug["llm_chat_surface_intent_knowledge_query"] = best_query or clean_text
        debug["llm_chat_surface_intent_store_overview_request"] = query_is_store_overview
        return SurfaceIntentClassificationResult(
            intent_family="knowledge_other",
            knowledge_query=best_query or clean_text,
            reason="vector_knowledge_probe",
            confidence=best_relevance,
            store_overview_request=query_is_store_overview,
            llm_call_count=0,
            debug=debug,
        )
    except Exception as exc:
        debug["llm_chat_surface_intent_error"] = str(exc)
        logger.warning("vector knowledge probe failed: %s", exc)
        return SurfaceIntentClassificationResult(intent_family="unclear", debug=debug)


async def classify_chat_surface_intent(
    *,
    user_text: str,
    locale: str | None,
    channel: str | None,
    sku_tokens: Sequence[str] | None = None,
    db: AsyncSession | None = None,
) -> SurfaceIntentClassificationResult:
    del db
    understanding = await build_understanding_result(
        user_text=user_text,
        locale=locale,
        channel=channel,
        sku_tokens=sku_tokens,
    )
    tags = {
        str(tag or "").strip().lower()
        for tag in list((understanding.entity_hints or {}).get("knowledge_tags") or [])
        if str(tag or "").strip()
    }
    workflow = str(understanding.workflow_hypothesis or "").strip().lower()
    if workflow == "company_info" and "contact" in tags:
        family = "support_contact"
    elif workflow in {"company_info", "policy_info"}:
        family = "knowledge_other"
    elif workflow in {"catalog_search", "product_detail", "mixed"}:
        family = "catalog"
    elif workflow == "off_topic":
        family = "off_topic"
    else:
        family = "unclear"
    debug = dict(understanding.debug or {})
    debug["llm_chat_surface_intent_family"] = family
    debug["llm_chat_surface_intent_confidence"] = understanding.intent_confidence
    debug["llm_chat_surface_intent_reason"] = understanding.reason
    debug["llm_chat_surface_intent_knowledge_query"] = understanding.knowledge_query
    return SurfaceIntentClassificationResult(
        intent_family=family,
        knowledge_query=str(understanding.knowledge_query or ""),
        reason=str(understanding.reason or ""),
        confidence=float(understanding.intent_confidence or 0.0),
        store_overview_request=bool(understanding.store_overview_request),
        llm_call_count=int(understanding.llm_call_count or 0),
        debug=debug,
    )


def _build_detail_inference_from_llm_data(
    *,
    llm_data: Mapping[str, Any] | None,
    alias_map: Mapping[str, Dict[str, str]] | None,
    allowed_exact_attributes: Sequence[str],
    allowed_soft_attributes: Sequence[str],
    confidence: float,
    min_confidence: float,
    debug: Dict[str, Any],
) -> DetailQueryInferenceResult:
    requested_fields = _normalize_requested_fields((llm_data or {}).get("requested_fields"))
    attribute_filters = _normalize_candidate_filters(
        filters=(llm_data or {}).get("attribute_filters"),
        alias_map=alias_map,
        allowed_attributes=list(allowed_exact_attributes) + list(allowed_soft_attributes),
    )
    semantic_hints = _normalize_semantic_hints((llm_data or {}).get("semantic_hints"))
    clarify_focus = normalize_focus_key((llm_data or {}).get("clarify_focus"))
    wants_image = bool((llm_data or {}).get("wants_image", False))

    debug["llm_detail_query_confidence"] = confidence
    debug["llm_detail_query_requested_fields"] = list(requested_fields)
    debug["llm_detail_query_attribute_keys"] = list(attribute_filters.keys())
    debug["llm_detail_query_semantic_hints"] = list(semantic_hints)
    debug["llm_detail_query_clarify_focus"] = clarify_focus

    trusted_llm_output = confidence >= min_confidence
    if not trusted_llm_output:
        requested_fields = []
        attribute_filters = {}
        semantic_hints = []
        wants_image = False
        clarify_focus = clarify_focus or "detail_request_needs_specific_product"

    return DetailQueryInferenceResult(
        requested_fields=requested_fields,
        attribute_filters=attribute_filters,
        wants_image=wants_image,
        semantic_hints=semantic_hints,
        clarify_focus=clarify_focus,
        confidence=confidence if trusted_llm_output else 0.0,
        llm_call_count=1,
        debug=debug,
    )


async def infer_detail_query(
    *,
    user_text: str,
    workflow: str,
    alias_map: Mapping[str, Dict[str, str]] | None,
    parser_rules: ParserRuleSet | None,
    existing_filters: Mapping[str, str] | None = None,
) -> DetailQueryInferenceResult:
    clean_workflow = normalize_text(workflow)
    debug: Dict[str, Any] = {
        "llm_detail_query_enabled": bool(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_ENABLED", True)),
        "llm_detail_query_used": False,
        "llm_detail_query_confidence": 0.0,
        "llm_detail_query_requested_fields": [],
        "llm_detail_query_attribute_keys": [],
        "llm_detail_query_semantic_hints": [],
        "llm_detail_query_clarify_focus": "",
    }
    if clean_workflow != "catalog":
        return DetailQueryInferenceResult(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            semantic_hints=[],
            clarify_focus="",
            debug=debug,
        )

    llm_enabled = bool(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_ENABLED", True))
    if not llm_enabled:
        return DetailQueryInferenceResult(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            semantic_hints=[],
            clarify_focus="",
            debug=debug,
        )

    allowed_exact_attributes = _allowed_exact_attributes(parser_rules)
    allowed_soft_attributes = _allowed_soft_attributes(parser_rules)
    model = str(
        getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MODEL", "")
        or getattr(settings, "NLU_MODEL", "gpt-5-mini")
    ).strip()
    max_tokens = int(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MAX_TOKENS", 220))
    min_confidence = float(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MIN_CONFIDENCE", 0.55))
    system_prompt = (
        "You interpret detail requests for a body jewelry ecommerce assistant. "
        "Return strict JSON with keys: requested_fields, attribute_filters, wants_image, semantic_hints, clarify_focus, confidence. "
        "requested_fields must be an array using only fields from: price, stock, image, attributes, name, sku. "
        "attribute_filters must only contain supported product attributes. "
        "semantic_hints must be up to 4 short concepts that should influence search but are not exact filters. "
        "If the request is ambiguous, set clarify_focus to a family key rather than a one-off term. "
        f"Supported ambiguity families: {', '.join(AMBIGUITY_FAMILY_KEYS)}. "
        "If the request is unclear, set clarify_focus to detail_request_needs_specific_product. "
        "Do not invent unsupported fields or filters."
    )
    user_payload = {
        "query": str(user_text or ""),
        "workflow": clean_workflow,
        "existing_filters": dict(existing_filters or {}),
        "allowed_exact_attributes": list(allowed_exact_attributes),
        "allowed_soft_attributes": list(allowed_soft_attributes),
        "supported_ambiguity_families": list(AMBIGUITY_FAMILY_KEYS),
    }

    llm_call_count = 0
    confidence = 0.0
    requested_fields: List[str] = []
    attribute_filters: Dict[str, str] = {}
    semantic_hints: List[str] = []
    clarify_focus = ""
    wants_image = False
    try:
        llm_data = await llm_service.generate_chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
            ],
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
            usage_kind="chat_detail_query_inference",
        )
        llm_call_count = 1
        debug["llm_detail_query_used"] = True
        try:
            confidence = float((llm_data or {}).get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        detail_result = _build_detail_inference_from_llm_data(
            llm_data=llm_data,
            alias_map=alias_map,
            allowed_exact_attributes=allowed_exact_attributes,
            allowed_soft_attributes=allowed_soft_attributes,
            confidence=confidence,
            min_confidence=min_confidence,
            debug=debug,
        )
        requested_fields = list(detail_result.requested_fields or [])
        attribute_filters = dict(detail_result.attribute_filters or {})
        semantic_hints = list(detail_result.semantic_hints or [])
        clarify_focus = str(detail_result.clarify_focus or "")
        wants_image = bool(detail_result.wants_image)
    except Exception as exc:
        debug["llm_detail_query_error"] = str(exc)
        logger.warning("llm detail query inference failed: %s", exc)
        return DetailQueryInferenceResult(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            semantic_hints=[],
            clarify_focus="detail_request_needs_specific_product",
            confidence=0.0,
            llm_call_count=llm_call_count,
            debug=debug,
        )

    detail_result = DetailQueryInferenceResult(
        requested_fields=requested_fields,
        attribute_filters=attribute_filters,
        wants_image=wants_image,
        semantic_hints=semantic_hints,
        clarify_focus=clarify_focus,
        confidence=confidence if confidence >= min_confidence else 0.0,
        llm_call_count=llm_call_count,
        debug=debug,
    )
    return detail_result


async def infer_chat_interpretation(
    *,
    user_text: str,
    locale: str | None,
    channel: str | None,
    alias_map: Mapping[str, Dict[str, str]] | None,
    parser_rules: ParserRuleSet | None,
    sku_tokens: Sequence[str] | None = None,
    existing_filters: Mapping[str, str] | None = None,
    db: AsyncSession | None = None,
) -> ChatInterpretationResult:
    del db
    understanding = await build_understanding_result(
        user_text=user_text,
        locale=locale,
        channel=channel,
        sku_tokens=sku_tokens,
    )
    capabilities = build_chat_runtime_capabilities()
    decision_state = build_decision_state(
        understanding=understanding,
        user_text=user_text,
        channel=channel,
        capabilities=capabilities,
    )
    execution_decision = decision_state.execution_decision
    if execution_decision is None:
        fallback = routing_policy._fallback_workflow_decision(reason="staged_decision_missing")
        execution_decision = routing_policy.ExecutionDecision(
            route_decision=fallback,
            execution_mode="component",
            reason="staged_decision_missing",
            feature_enabled=False,
            channel_allowed=False,
            tool_suitable=False,
            selection_source="staged_fallback",
        )

    if decision_state.internal_workflow in {"catalog_search", "product_detail", "mixed"}:
        detail = await infer_detail_query(
            user_text=user_text,
            workflow="catalog",
            alias_map=alias_map,
            parser_rules=parser_rules,
            existing_filters=existing_filters,
        )
        if decision_state.internal_workflow == "product_detail" and not (detail.requested_fields or detail.wants_image):
            detail = replace(
                detail,
                requested_fields=["attributes"],
                confidence=max(float(detail.confidence or 0.0), float(understanding.intent_confidence or 0.0)),
            )
    else:
        detail = DetailQueryInferenceResult(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            semantic_hints=[],
            clarify_focus="",
            confidence=0.0,
            llm_call_count=0,
            debug={},
        )

    debug: Dict[str, Any] = {}
    debug.update(dict(understanding.debug or {}))
    debug.update(dict(detail.debug or {}))
    debug["llm_chat_interpretation_used"] = bool(understanding.llm_call_count or detail.llm_call_count)
    debug["llm_chat_interpretation_confidence"] = decision_state.intent_confidence
    debug["llm_chat_interpretation_workflow"] = decision_state.public_workflow
    debug["llm_chat_interpretation_internal_workflow"] = decision_state.internal_workflow
    debug["llm_chat_interpretation_execution_mode"] = execution_decision.execution_mode
    debug["llm_chat_interpretation_reason"] = decision_state.reason
    debug["llm_chat_interpretation_surface_short_circuit"] = str(understanding.debug.get("understanding_source") or "") == "deterministic"

    return ChatInterpretationResult(
        execution_decision=execution_decision,
        detail=detail,
        llm_call_count=int(understanding.llm_call_count or 0) + int(detail.llm_call_count or 0),
        debug=debug,
    )


async def infer_attribute_list_target(
    *,
    user_text: str,
    workflow: str,
) -> AttributeListTargetResult:
    clean_workflow = normalize_text(workflow)
    clean_text = normalize_text(user_text)
    debug: Dict[str, Any] = {
        "llm_attribute_list_target_enabled": bool(
            getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_ENABLED", True)
        ),
        "llm_attribute_list_target_used": False,
        "llm_attribute_list_target_confidence": 0.0,
        "llm_attribute_list_target_value": "",
    }
    if clean_workflow != "catalog" or not clean_text:
        return AttributeListTargetResult(target="", debug=debug)

    model = str(
        getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MODEL", "")
        or getattr(settings, "NLU_MODEL", "gpt-5-mini")
    ).strip()
    max_tokens = int(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MAX_TOKENS", 60))
    try:
        llm_data = await llm_service.generate_chat_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the catalog facet-list target for the user's question. "
                        "Return strict JSON with keys target and confidence. "
                        "Choose exactly one target from: "
                        f"{', '.join(sorted(ATTRIBUTE_LIST_TARGETS))}. "
                        "If the question is not asking for a list of facet values, return target as an empty string. "
                        "Prefer the most specific target that matches the user's wording. "
                        "Do not guess product details or return multiple targets."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "query": str(user_text or ""),
                            "workflow": clean_workflow,
                            "supported_targets": sorted(ATTRIBUTE_LIST_TARGETS),
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
            usage_kind="chat_attribute_list_target",
        )
        raw_target = _normalize_attribute_list_target((llm_data or {}).get("target"))
        try:
            confidence = float((llm_data or {}).get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        debug["llm_attribute_list_target_used"] = bool(raw_target)
        debug["llm_attribute_list_target_confidence"] = confidence
        debug["llm_attribute_list_target_value"] = raw_target
        return AttributeListTargetResult(
            target=raw_target,
            confidence=confidence,
            llm_call_count=1,
            debug=debug,
        )
    except Exception as exc:
        debug["llm_attribute_list_target_error"] = str(exc)
        logger.warning("llm attribute list target classification failed: %s", exc)
        return AttributeListTargetResult(target="", debug=debug)


async def enrich_product_attribute_filters(
    *,
    db: AsyncSession,
    user_text: str,
    workflow: str,
    existing_filters: Mapping[str, str] | None,
    alias_map: Mapping[str, Dict[str, str]] | None,
    parser_rules: ParserRuleSet | None,
) -> AttributeExtractionResult:
    clean_workflow = normalize_text(workflow)
    allowed_exact_attributes = _allowed_exact_attributes(parser_rules)
    allowed_soft_attributes = _allowed_soft_attributes(parser_rules)
    existing_exact_filters = {
        key: value
        for key, value in dict(existing_filters or {}).items()
        if normalize_text(key) in HARD_FILTER_KEYS and str(value or "").strip()
    }
    debug: Dict[str, Any] = {
        "llm_attribute_interpretation_enabled": bool(
            getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_ENABLED", True)
        ),
        "llm_attribute_interpretation_used": False,
        "llm_attribute_interpretation_confidence": 0.0,
        "llm_exact_filter_keys": [],
        "llm_soft_filter_keys": [],
        "semantic_hint_keys": [],
        "semantic_hint_clarify_focus": "",
        "semantic_hint_source": "",
    }

    if clean_workflow != "catalog":
        return AttributeExtractionResult(
            exact_filters={},
            semantic_hints=[],
            soft_filters={},
            clarify_focus="",
            debug=debug,
        )

    llm_enabled = bool(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_ENABLED", True))
    should_invoke_llm = bool(llm_enabled)

    if not should_invoke_llm:
        return AttributeExtractionResult(
            exact_filters={},
            semantic_hints=[],
            soft_filters={},
            clarify_focus="",
            debug=debug,
        )

    model = str(
        getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MODEL", "")
        or getattr(settings, "NLU_MODEL", "gpt-5-mini")
    ).strip()
    max_tokens = int(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MAX_TOKENS", 220))
    min_confidence = float(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MIN_CONFIDENCE", 0.55))

    system_prompt = (
        "You interpret product-search intent for a body jewelry ecommerce assistant. "
        "Return strict JSON with keys: exact_filters, soft_filters, semantic_hints, clarify_focus, confidence. "
        "When a concept is ambiguous, clarify_focus must be a family key rather than a one-off term. "
        f"Supported ambiguity families: {', '.join(AMBIGUITY_FAMILY_KEYS)}. "
        "`exact_filters` must use only the provided allowed exact attributes for hard constraints. "
        "`soft_filters` must use only the provided allowed soft attributes for style or family cues. "
        "`semantic_hints` must be an array of up to 4 short concept strings for ambiguous or discovery-style concepts "
        "that should influence semantic search instead of structured filters. "
        "If the query says sterilization or a similar ambiguous condition concept, do not force it into a facet; "
        "return it as a semantic hint and set clarify_focus to `condition`. "
        "Do not invent unsupported exact filters."
    )
    user_payload = {
        "query": str(user_text or ""),
        "workflow": clean_workflow,
        "existing_filters": dict(existing_filters or {}),
        "allowed_exact_attributes": list(allowed_exact_attributes),
        "allowed_soft_attributes": list(allowed_soft_attributes),
        "supported_ambiguity_families": list(AMBIGUITY_FAMILY_KEYS),
    }

    llm_call_count = 0
    llm_confidence = 0.0
    llm_exact_filters: Dict[str, str] = {}
    llm_soft_filters: Dict[str, str] = {}
    llm_semantic_hints: List[str] = []
    llm_clarify_focus = ""
    try:
        llm_data = await llm_service.generate_chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
            ],
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
            usage_kind="chat_attribute_interpretation",
        )
        llm_call_count = 1
        debug["llm_attribute_interpretation_used"] = True
        try:
            llm_confidence = float((llm_data or {}).get("confidence") or 0.0)
        except Exception:
            llm_confidence = 0.0
        llm_exact_filters = _normalize_candidate_filters(
            filters=(llm_data or {}).get("exact_filters"),
            alias_map=alias_map,
            allowed_attributes=allowed_exact_attributes,
        )
        llm_soft_filters = _normalize_candidate_filters(
            filters=(llm_data or {}).get("soft_filters"),
            alias_map=alias_map,
            allowed_attributes=allowed_soft_attributes,
        )
        llm_semantic_hints = _normalize_semantic_hints((llm_data or {}).get("semantic_hints"))
        llm_clarify_focus = normalize_focus_key((llm_data or {}).get("clarify_focus"))
    except Exception as exc:
        debug["llm_attribute_interpretation_error"] = str(exc)
        logger.warning("llm attribute interpretation failed: %s", exc)

    debug["llm_attribute_interpretation_confidence"] = llm_confidence
    trusted_llm_output = llm_confidence >= min_confidence

    validated_exact_filters: Dict[str, str] = {}
    if trusted_llm_output and llm_exact_filters and hasattr(db, "execute"):
        proposed_exact_filters = {
            key: value
            for key, value in llm_exact_filters.items()
            if key not in existing_exact_filters
        }
        validated_exact_filters = await _validate_attribute_filters(
            db,
            filters=proposed_exact_filters,
            alias_map=alias_map,
            allowed_attributes=allowed_exact_attributes,
        )

    soft_filters: Dict[str, str] = {}
    if trusted_llm_output and llm_soft_filters:
        soft_filters = dict(llm_soft_filters)

    semantic_hints = list(llm_semantic_hints) if trusted_llm_output else []
    clarify_focus = str(llm_clarify_focus or "") if trusted_llm_output else ""

    debug["llm_exact_filter_keys"] = list(validated_exact_filters.keys())
    debug["llm_soft_filter_keys"] = list(soft_filters.keys())
    debug["semantic_hint_keys"] = list(semantic_hints)
    debug["semantic_hint_clarify_focus"] = clarify_focus
    if semantic_hints:
        debug["semantic_hint_source"] = "llm"

    return AttributeExtractionResult(
        exact_filters=validated_exact_filters,
        semantic_hints=semantic_hints,
        soft_filters=soft_filters,
        clarify_focus=clarify_focus,
        confidence=llm_confidence if trusted_llm_output else 0.0,
        llm_call_count=llm_call_count,
        debug=debug,
    )
