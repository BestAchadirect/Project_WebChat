from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product_attribute import AttributeDefinition, FacetValueAlias, ProductAttributeValue
from app.services.ai.llm_service import llm_service
from app.services.chat.parsing.attribute_normalization import (
    normalize_attribute_value,
    normalize_lexical_alias_map,
    normalize_text,
)
from app.services.chat.parsing.parser_rule_types import ParserRuleSet, empty_rule_set
from app.services.chat.parsing.search_policy import HARD_FILTER_KEYS

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
    return sorted(
        {
            "category",
            "color",
            "crystal_color",
            "design",
            "finish",
            "jewelry_type",
            "material",
            "opal_color",
            "pearl_color",
            "stone",
            "threading",
        }
    )


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


def _normalize_focus_key(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")


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

    if clean_workflow not in {"catalog", "recommendation"}:
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
        "`exact_filters` must be an object using only attributes from the allowed exact attribute list, "
        "and only for clear exact constraints like gauge, threading, or exact size fields. "
        "`soft_filters` must be an object using only attributes from the allowed soft attribute list, "
        "and should capture obvious product-family or style constraints such as material, jewelry_type, color, "
        "finish, design, threading, category, or stone-related cues. "
        "`semantic_hints` must be an array of up to 4 short concept strings for ambiguous or discovery-style concepts "
        "that should influence semantic search instead of structured filters. "
        "If the query says sterilization or a similar ambiguous sterilization concept, do not force it into a facet; "
        "return it as a semantic hint and set clarify_focus to `sterilization_meaning`. "
        "Do not invent unsupported exact filters."
    )
    user_payload = {
        "query": str(user_text or ""),
        "workflow": clean_workflow,
        "existing_filters": dict(existing_filters or {}),
        "allowed_exact_attributes": list(allowed_exact_attributes),
        "allowed_soft_attributes": list(allowed_soft_attributes),
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
        llm_clarify_focus = _normalize_focus_key((llm_data or {}).get("clarify_focus"))
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
