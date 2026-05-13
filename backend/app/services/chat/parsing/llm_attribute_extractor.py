from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from typing import Any, Dict, List, Mapping, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.prompts.ambiguity import AMBIGUITY_FAMILY_KEYS, normalize_focus_key
from app.models.product import Product
from app.models.product_attribute import AttributeDefinition, FacetValueAlias, ProductAttributeValue
from app.services.catalog.attributes_service import eav_service
from app.services.ai.llm_service import llm_service
from app.services.chat.parsing.attribute_keys import canonicalize_filter_key
from app.services.chat.parsing.attribute_normalization import normalize_attribute_value, normalize_text
from app.services.chat.parsing.parser_rule_types import ParserRuleSet, empty_rule_set
from app.services.chat.parsing.search_policy import HARD_FILTER_KEYS
import app.services.chat.routing.routing_policy as routing_policy
from app.services.chat.routing.decision_engine import build_decision_state
from app.services.chat.routing.understanding import build_understanding_result
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.knowledge.retrieval import KnowledgeRetrievalService
from app.services.knowledge.tagging import build_knowledge_query_tags

ATTRIBUTE_LIST_TARGETS = frozenset(
    {
        "body_part",
        "feature",
        "jewelry_type",
        "material",
        "presentation_type",
        "color",
        "gauge",
        "threading",
        "theme",
    }
)

DEFAULT_SOFT_ATTRIBUTE_KEYS = frozenset(
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
        "theme",
        "stone",
        "threading",
    }
)

logger = logging.getLogger(__name__)

INTERNAL_ATTRIBUTE_KEYS = frozenset({"source_id", "source_raw_sku"})
VALUE_CANDIDATE_STOPWORDS = frozenset(
    {
        "and",
        "any",
        "are",
        "as",
        "available",
        "be",
        "by",
        "can",
        "catalog",
        "color",
        "colors",
        "diameter",
        "do",
        "does",
        "find",
        "for",
        "from",
        "gauge",
        "get",
        "have",
        "height",
        "i",
        "in",
        "is",
        "jewelry",
        "length",
        "looking",
        "made",
        "me",
        "mean",
        "my",
        "need",
        "of",
        "option",
        "options",
        "or",
        "policy",
        "please",
        "product",
        "products",
        "refund",
        "refunds",
        "return",
        "returns",
        "see",
        "show",
        "size",
        "style",
        "tell",
        "the",
        "to",
        "type",
        "types",
        "want",
        "what",
        "with",
        "you",
        "your",
    }
)


def _attribute_reasoning_effort() -> str:
    return str(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_REASONING_EFFORT", "low") or "low").strip() or "low"


def _attribute_timeout_seconds() -> float:
    try:
        return max(8.0, float(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_TIMEOUT_SECONDS", 30.0) or 30.0))
    except Exception:
        return 30.0


def _detail_query_max_tokens() -> int:
    try:
        return max(1200, int(getattr(settings, "CHAT_DETAIL_QUERY_MAX_TOKENS", 1200) or 1200))
    except Exception:
        return 1200


def _understanding_hint_bool(understanding: Any, key: str) -> bool:
    return bool(dict(getattr(understanding, "entity_hints", {}) or {}).get(key))


def _understanding_hint_text(understanding: Any, key: str) -> str:
    return str(dict(getattr(understanding, "entity_hints", {}) or {}).get(key) or "").strip()


@dataclass(frozen=True)
class AttributeExtractionResult:
    exact_filters: Dict[str, str]
    semantic_hints: List[str]
    unknown_terms: List[str] = field(default_factory=list)
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
    unknown_terms: List[str]
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


def _canonical_attribute_names(values: Sequence[str] | None) -> set[str]:
    return {
        canonicalize_filter_key(item)
        for item in list(values or [])
        if canonicalize_filter_key(item) and canonicalize_filter_key(item) not in INTERNAL_ATTRIBUTE_KEYS
    }


async def _load_searchable_attribute_names(db: AsyncSession | None) -> List[str]:
    if db is None or not hasattr(db, "execute"):
        return []
    try:
        return await eav_service.get_searchable_attribute_names(db)
    except Exception as exc:
        logger.warning("searchable attribute metadata unavailable: %s", exc)
        return []


async def _load_searchable_attribute_metadata(db: AsyncSession | None) -> List[Dict[str, Any]]:
    if db is None or not hasattr(db, "execute"):
        return []
    try:
        return await eav_service.get_searchable_attribute_metadata(db)
    except Exception as exc:
        logger.warning("searchable attribute metadata unavailable: %s", exc)
        return []


def _normalize_attribute_metadata(values: Sequence[Mapping[str, Any]] | None) -> List[Dict[str, Any]]:
    metadata: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(values or []):
        item = dict(raw or {})
        name = canonicalize_filter_key(item.get("name"))
        if not name or name in INTERNAL_ATTRIBUTE_KEYS or name in seen:
            continue
        seen.add(name)
        metadata.append(
            {
                "name": name,
                "display_name": str(item.get("display_name") or name.replace("_", " ").title()),
                "data_type": str(item.get("data_type") or "string"),
                "is_multivalue": bool(item.get("is_multivalue")) or name == "category",
            }
        )
    return metadata


def _attribute_names_from_metadata(values: Sequence[Mapping[str, Any]] | None) -> List[str]:
    return [str(item.get("name") or "").strip() for item in _normalize_attribute_metadata(values)]


async def _resolve_searchable_attribute_context(
    *,
    db: AsyncSession | None,
    searchable_attribute_names: Sequence[str] | None = None,
    searchable_attribute_metadata: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[List[str], List[Dict[str, Any]]]:
    metadata = _normalize_attribute_metadata(searchable_attribute_metadata)
    names = list(searchable_attribute_names or [])
    if metadata and not names:
        names = _attribute_names_from_metadata(metadata)
    if not metadata and db is not None and hasattr(db, "execute"):
        metadata = await _load_searchable_attribute_metadata(db)
        if not names and metadata:
            names = _attribute_names_from_metadata(metadata)
    if not names:
        names = await _load_searchable_attribute_names(db)
    if not metadata:
        metadata = [
            {
                "name": canonicalize_filter_key(name),
                "display_name": canonicalize_filter_key(name).replace("_", " ").title(),
                "data_type": "string",
                "is_multivalue": canonicalize_filter_key(name) == "category",
            }
            for name in names
            if canonicalize_filter_key(name)
        ]
    return list(names), _normalize_attribute_metadata(metadata)


def _query_value_candidate_tokens(user_text: str) -> List[str]:
    text = normalize_text(user_text)
    if not text:
        return []
    tokens: List[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", text):
        token = raw.strip()
        if len(token) < 2 or token in VALUE_CANDIDATE_STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= 12:
            break
    return tokens


def _query_value_candidate_lookup_terms(tokens: Sequence[str]) -> List[str]:
    """Build generic lookup terms for DB value retrieval without deciding the attribute."""
    lookup_terms: List[str] = []
    seen: set[str] = set()
    for raw in list(tokens or []):
        token = normalize_text(raw)
        if not token or token in VALUE_CANDIDATE_STOPWORDS:
            continue
        candidates = [token]
        if len(token) >= 7:
            candidates.append(token[:6])
        if len(token) >= 4 and token.endswith("s"):
            candidates.append(token[:-1])
        for candidate in candidates:
            if len(candidate) < 3 or candidate in seen:
                continue
            seen.add(candidate)
            lookup_terms.append(candidate)
    return lookup_terms


def _matched_attribute_lookup_terms(*, value_norm: str, tokens: Sequence[str]) -> List[str]:
    clean_value = normalize_text(value_norm)
    if not clean_value:
        return []
    matches: List[str] = []
    seen: set[str] = set()
    for term in _query_value_candidate_lookup_terms(tokens):
        if term and term in clean_value and term not in seen:
            seen.add(term)
            matches.append(term)
    return matches


def _score_attribute_value_candidate(*, value_norm: str, tokens: Sequence[str], count: int) -> float:
    clean_value = normalize_text(value_norm)
    if not clean_value or not tokens:
        return 0.0
    matched = [token for token in tokens if token and token in clean_value]
    lookup_matched = _matched_attribute_lookup_terms(value_norm=clean_value, tokens=tokens)
    if not matched and not lookup_matched:
        return 0.0
    lookup_terms = set(_query_value_candidate_lookup_terms(tokens))
    exact_weight = float(len(matched))
    lookup_weight = 0.6 * float(len([term for term in lookup_matched if term not in matched]))
    coverage = min(1.0, (exact_weight + lookup_weight) / max(1.0, float(len(tokens))))
    ordered_query = " ".join(tokens)
    exact_value_bonus = 7.0 if clean_value in lookup_terms else 0.0
    phrase_bonus = 4.0 if ordered_query and ordered_query in clean_value else 0.0
    count_bonus = min(3.0, max(0.0, float(count or 0) / 10000.0))
    return round((coverage * 10.0) + exact_value_bonus + phrase_bonus + count_bonus, 4)


def _score_approximate_attribute_value_candidate(
    *,
    value_norm: str,
    tokens: Sequence[str],
    count: int,
) -> tuple[float, List[str]]:
    clean_value = normalize_text(value_norm)
    if not clean_value or not tokens:
        return 0.0, []
    value_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", clean_value)
        if len(token) >= 4 and token not in VALUE_CANDIDATE_STOPWORDS
    ]
    if not value_tokens:
        return 0.0, []
    best_score = 0.0
    matched_terms: List[str] = []
    for token in list(tokens or []):
        if len(token) < 5:
            continue
        token_best = max(SequenceMatcher(None, token, value_token).ratio() for value_token in value_tokens)
        if token_best > best_score:
            best_score = token_best
        if token_best >= 0.84:
            matched_terms.append(token)
    if best_score < 0.84 or not matched_terms:
        return 0.0, []
    count_bonus = min(2.0, max(0.0, float(count or 0) / 10000.0))
    return round((best_score * 8.0) + count_bonus, 4), list(dict.fromkeys(matched_terms))


async def _load_attribute_value_candidates(
    *,
    db: AsyncSession | None,
    user_text: str,
    allowed_attributes: Sequence[str],
    total_limit: int = 30,
    per_attribute_limit: int = 6,
) -> List[Dict[str, Any]]:
    """Load DB-backed facet values that overlap the user's product wording."""
    if db is None or not hasattr(db, "execute"):
        return []
    tokens = _query_value_candidate_tokens(user_text)
    allowed = _canonical_attribute_names(allowed_attributes)
    if not tokens or not allowed:
        return []

    value_expr = func.lower(func.coalesce(ProductAttributeValue.value_norm, ProductAttributeValue.value, ""))
    lookup_terms = _query_value_candidate_lookup_terms(tokens)
    conditions = [value_expr.like(f"%{token}%") for token in lookup_terms]
    if not conditions:
        return []

    rows: List[Any] = []
    try:
        stmt = (
            select(
                AttributeDefinition.name,
                ProductAttributeValue.value,
                ProductAttributeValue.value_norm,
                func.count(Product.id).label("product_count"),
            )
            .join(ProductAttributeValue, ProductAttributeValue.attribute_id == AttributeDefinition.id)
            .join(Product, Product.id == ProductAttributeValue.product_id)
            .where(AttributeDefinition.is_enabled.is_(True))
            .where(func.lower(AttributeDefinition.name).in_(sorted(allowed)))
            .where(Product.is_active.is_(True))
            .where(or_(*conditions))
            .group_by(
                AttributeDefinition.name,
                ProductAttributeValue.value,
                ProductAttributeValue.value_norm,
            )
            .limit(max(total_limit * 8, 80))
        )
        rows = (await db.execute(stmt)).all()
    except Exception as exc:
        logger.warning("catalog attribute value candidate lookup failed: %s", exc)
        rows = []

    candidates: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    per_attribute_counts: Dict[str, int] = {}
    for raw_attribute, raw_value, raw_value_norm, raw_count in rows:
        attribute = canonicalize_filter_key(raw_attribute)
        value = str(raw_value or "").strip()
        value_norm = normalize_text(raw_value_norm or raw_value)
        if not attribute or not value or not value_norm:
            continue
        score = _score_attribute_value_candidate(
            value_norm=value_norm,
            tokens=tokens,
            count=int(raw_count or 0),
        )
        if score <= 0:
            continue
        key = (attribute, value_norm)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "attribute": attribute,
                "value": value,
                "value_norm": value_norm,
                "matched_terms": _matched_attribute_lookup_terms(value_norm=value_norm, tokens=tokens),
                "product_count": int(raw_count or 0),
                "score": score,
            }
        )

    if len(candidates) < max(3, min(total_limit, 10)):
        try:
            broad_stmt = (
                select(
                    AttributeDefinition.name,
                    ProductAttributeValue.value,
                    ProductAttributeValue.value_norm,
                    func.count(Product.id).label("product_count"),
                )
                .join(ProductAttributeValue, ProductAttributeValue.attribute_id == AttributeDefinition.id)
                .join(Product, Product.id == ProductAttributeValue.product_id)
                .where(AttributeDefinition.is_enabled.is_(True))
                .where(func.lower(AttributeDefinition.name).in_(sorted(allowed)))
                .where(Product.is_active.is_(True))
                .where(ProductAttributeValue.value_norm.isnot(None))
                .where(ProductAttributeValue.value_norm != "")
                .group_by(
                    AttributeDefinition.name,
                    ProductAttributeValue.value,
                    ProductAttributeValue.value_norm,
                )
            )
            broad_rows = (await db.execute(broad_stmt)).all()
        except Exception as exc:
            logger.warning("catalog approximate attribute value lookup failed: %s", exc)
            broad_rows = []

        for raw_attribute, raw_value, raw_value_norm, raw_count in broad_rows:
            attribute = canonicalize_filter_key(raw_attribute)
            value = str(raw_value or "").strip()
            value_norm = normalize_text(raw_value_norm or raw_value)
            if not attribute or not value or not value_norm:
                continue
            key = (attribute, value_norm)
            if key in seen:
                continue
            score, matched_terms = _score_approximate_attribute_value_candidate(
                value_norm=value_norm,
                tokens=tokens,
                count=int(raw_count or 0),
            )
            if score <= 0:
                continue
            seen.add(key)
            candidates.append(
                {
                    "attribute": attribute,
                    "value": value,
                    "value_norm": value_norm,
                    "matched_terms": matched_terms,
                    "product_count": int(raw_count or 0),
                    "score": score,
                    "match_type": "approximate",
                }
            )

    candidates.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            -int(item.get("product_count") or 0),
            str(item.get("attribute") or ""),
            str(item.get("value") or ""),
        )
    )
    limited: List[Dict[str, Any]] = []
    for candidate in candidates:
        attribute = str(candidate.get("attribute") or "")
        count = per_attribute_counts.get(attribute, 0)
        if count >= max(1, per_attribute_limit):
            continue
        per_attribute_counts[attribute] = count + 1
        limited.append(candidate)
        if len(limited) >= max(1, total_limit):
            break
    return limited


async def _load_attribute_value_options(
    *,
    db: AsyncSession | None,
    allowed_attributes: Sequence[str],
    max_values_per_attribute: int = 30,
    total_limit: int = 120,
) -> List[Dict[str, Any]]:
    """Load compact DB-backed option lists for low-cardinality searchable attributes."""
    if db is None or not hasattr(db, "execute"):
        return []
    allowed = _canonical_attribute_names(allowed_attributes)
    if not allowed:
        return []

    try:
        stmt = (
            select(
                AttributeDefinition.name,
                ProductAttributeValue.value,
                ProductAttributeValue.value_norm,
                func.count(Product.id).label("product_count"),
            )
            .join(ProductAttributeValue, ProductAttributeValue.attribute_id == AttributeDefinition.id)
            .join(Product, Product.id == ProductAttributeValue.product_id)
            .where(AttributeDefinition.is_enabled.is_(True))
            .where(func.lower(AttributeDefinition.name).in_(sorted(allowed)))
            .where(Product.is_active.is_(True))
            .where(ProductAttributeValue.value_norm.isnot(None))
            .where(ProductAttributeValue.value_norm != "")
            .group_by(
                AttributeDefinition.name,
                ProductAttributeValue.value,
                ProductAttributeValue.value_norm,
            )
        )
        rows = (await db.execute(stmt)).all()
    except Exception as exc:
        logger.warning("catalog attribute value option lookup failed: %s", exc)
        return []

    grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for raw_attribute, raw_value, raw_value_norm, raw_count in rows:
        attribute = canonicalize_filter_key(raw_attribute)
        value = str(raw_value or "").strip()
        value_norm = normalize_text(raw_value_norm or raw_value)
        if not attribute or not value or not value_norm:
            continue
        values = grouped.setdefault(attribute, {})
        existing = values.get(value_norm)
        count = int(raw_count or 0)
        if existing is None or count > int(existing.get("product_count") or 0):
            values[value_norm] = {
                "value": value,
                "value_norm": value_norm,
                "product_count": count,
            }

    options: List[Dict[str, Any]] = []
    for attribute in sorted(grouped):
        values = list(grouped[attribute].values())
        if not values or len(values) > max(1, int(max_values_per_attribute)):
            continue
        values.sort(
            key=lambda item: (
                -int(item.get("product_count") or 0),
                str(item.get("value_norm") or ""),
            )
        )
        options.append(
            {
                "attribute": attribute,
                "value_count": len(values),
                "values": values[: max(1, int(max_values_per_attribute))],
            }
        )
        if sum(len(item.get("values") or []) for item in options) >= max(1, int(total_limit)):
            break
    return options


def _allowed_exact_attributes(
    rule_set: ParserRuleSet | None,
    searchable_attribute_names: Sequence[str] | None = None,
) -> List[str]:
    active_rules = rule_set or empty_rule_set()
    declared = _canonical_attribute_names(active_rules.allowed_attribute_filters)
    searchable = _canonical_attribute_names(searchable_attribute_names)
    if searchable:
        return sorted(_canonical_attribute_names(HARD_FILTER_KEYS).intersection(searchable))
    if declared:
        return sorted(declared.intersection(HARD_FILTER_KEYS))
    return sorted(HARD_FILTER_KEYS)


def _allowed_soft_attributes(
    rule_set: ParserRuleSet | None,
    searchable_attribute_names: Sequence[str] | None = None,
) -> List[str]:
    active_rules = rule_set or empty_rule_set()
    declared = _canonical_attribute_names(active_rules.allowed_attribute_filters)
    searchable = _canonical_attribute_names(searchable_attribute_names)
    if searchable:
        return sorted(searchable.difference(HARD_FILTER_KEYS))
    if declared:
        return sorted(declared.difference(HARD_FILTER_KEYS))
    defaults = _canonical_attribute_names(DEFAULT_SOFT_ATTRIBUTE_KEYS)
    return sorted(defaults)


def _normalize_candidate_filters(
    *,
    filters: Mapping[str, Any] | None,
    allowed_attributes: Sequence[str],
) -> Dict[str, str]:
    allowed = {str(item or "").strip().lower() for item in list(allowed_attributes or []) if str(item or "").strip()}
    clean: Dict[str, str] = {}
    for raw_key, raw_value in dict(filters or {}).items():
        key = canonicalize_filter_key(raw_key)
        if not key or (allowed and key not in allowed):
            continue
        value = normalize_attribute_value(key=key, value=raw_value)
        if value:
            clean[key] = value
    return clean


def _split_normalized_filter_values(value: Any) -> List[str]:
    tokens: List[str] = []
    for raw in str(value or "").split(";;"):
        token = normalize_text(raw)
        if token:
            tokens.append(token)
    return tokens


def _candidate_values_share_lookup_term(*, value_norm: str, candidate_norm: str) -> bool:
    value_terms = {
        term
        for term in _query_value_candidate_lookup_terms(_query_value_candidate_tokens(value_norm))
        if len(term) >= 6
    }
    candidate_terms = {
        term
        for term in _query_value_candidate_lookup_terms(_query_value_candidate_tokens(candidate_norm))
        if len(term) >= 6
    }
    return bool(value_terms and candidate_terms and value_terms.intersection(candidate_terms))


def _align_candidate_filter_values(
    *,
    filters: Mapping[str, str],
    attribute_value_candidates: Sequence[Mapping[str, Any]] | None,
) -> Dict[str, str]:
    if not filters or not attribute_value_candidates:
        return dict(filters or {})

    candidates_by_attribute: Dict[str, List[Dict[str, Any]]] = {}
    for raw in list(attribute_value_candidates or []):
        item = dict(raw or {})
        attribute = canonicalize_filter_key(item.get("attribute"))
        value_norm = normalize_text(item.get("value_norm") or item.get("value"))
        if not attribute or not value_norm:
            continue
        item["attribute"] = attribute
        item["value_norm"] = value_norm
        candidates_by_attribute.setdefault(attribute, []).append(item)

    aligned: Dict[str, str] = {}
    for key, value in dict(filters or {}).items():
        attribute = canonicalize_filter_key(key)
        candidates = candidates_by_attribute.get(attribute) or []
        if not attribute or not candidates:
            aligned[attribute or key] = value
            continue

        selected: List[Dict[str, Any]] = []
        for value_norm in _split_normalized_filter_values(value):
            matches = [
                candidate
                for candidate in candidates
                if value_norm == str(candidate.get("value_norm") or "")
                or value_norm in str(candidate.get("value_norm") or "")
                or str(candidate.get("value_norm") or "") in value_norm
                or _candidate_values_share_lookup_term(
                    value_norm=value_norm,
                    candidate_norm=str(candidate.get("value_norm") or ""),
                )
            ]
            if not matches:
                selected.append(
                    {
                        "value_norm": value_norm,
                        "score": 0.0,
                        "product_count": 0,
                        "candidate_backed": False,
                    }
                )
                continue
            matches.sort(
                key=lambda item: (
                    -float(item.get("score") or 0.0),
                    -int(item.get("product_count") or 0),
                    str(item.get("value_norm") or ""),
                )
            )
            selected.append({**matches[0], "candidate_backed": True})

        collapsed: List[Dict[str, Any]] = []
        for item in sorted(
            selected,
            key=lambda candidate: (
                -float(candidate.get("score") or 0.0),
                -int(candidate.get("product_count") or 0),
                str(candidate.get("value_norm") or ""),
            ),
        ):
            item_norm = str(item.get("value_norm") or "")
            if not item_norm:
                continue
            if any(
                bool(item.get("candidate_backed"))
                and bool(existing.get("candidate_backed"))
                and (
                    item_norm in str(existing.get("value_norm") or "")
                    or str(existing.get("value_norm") or "") in item_norm
                )
                for existing in collapsed
            ):
                continue
            collapsed.append(item)

        values = [str(item.get("value_norm") or "").strip() for item in collapsed if str(item.get("value_norm") or "").strip()]
        if not values:
            continue
        aligned[attribute] = ";;".join(dict.fromkeys(values)) if attribute == "category" else values[0]
    return aligned


def _fallback_detail_from_attribute_candidates(
    *,
    attribute_value_candidates: Sequence[Mapping[str, Any]] | None,
    debug: Dict[str, Any],
    min_score: float = 6.0,
    confidence: float = 0.8,
) -> DetailQueryInferenceResult | None:
    candidates = [dict(item or {}) for item in list(attribute_value_candidates or [])]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            -int(item.get("product_count") or 0),
            str(item.get("attribute") or ""),
            str(item.get("value_norm") or item.get("value") or ""),
        )
    )
    top = candidates[0]
    attribute = canonicalize_filter_key(top.get("attribute"))
    value_norm = normalize_text(top.get("value_norm") or top.get("value"))
    score = float(top.get("score") or 0.0)
    matched_terms = [str(item or "").strip() for item in list(top.get("matched_terms") or []) if str(item or "").strip()]
    if not attribute or not value_norm or score < float(min_score) or not matched_terms:
        return None

    debug["llm_detail_query_fallback_source"] = "attribute_value_candidate"
    debug["llm_detail_query_fallback_filter"] = {
        "attribute": attribute,
        "value": value_norm,
        "score": score,
        "product_count": int(top.get("product_count") or 0),
    }
    return DetailQueryInferenceResult(
        requested_fields=[],
        attribute_filters={attribute: value_norm},
        wants_image=False,
        semantic_hints=[],
        unknown_terms=[],
        clarify_focus="",
        confidence=confidence,
        llm_call_count=0,
        debug=debug,
    )


async def _value_exists_for_attribute(
    db: AsyncSession,
    *,
    attribute_name: str,
    normalized_value: str,
) -> bool:
    clean_attribute = canonicalize_filter_key(attribute_name)
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


def _normalize_unknown_terms(raw_terms: Any) -> List[str]:
    terms: List[str] = []
    seen: set[str] = set()
    for raw in list(raw_terms or []):
        term = normalize_text(str(raw or ""))
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= 4:
            break
    return terms


def _normalize_attribute_list_target(raw_target: Any) -> str:
    text = normalize_text(str(raw_target or ""))
    if not text:
        return ""
    return text.replace("-", "_").replace(" ", "_").strip("_")


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
    has_company = _understanding_hint_bool(understanding, "has_company_signal")
    has_policy = _understanding_hint_bool(understanding, "has_policy_signal")
    has_product = _understanding_hint_bool(understanding, "has_product_signal")
    has_off_topic = _understanding_hint_bool(understanding, "has_off_topic_signal")
    knowledge_query = _understanding_hint_text(understanding, "preferred_knowledge_query") or str(
        understanding.knowledge_query or ""
    )
    store_overview_request = bool(
        _understanding_hint_bool(understanding, "preferred_store_overview_request")
        or understanding.store_overview_request
    )
    if has_company and "contact" in tags:
        family = "support_contact"
    elif has_company or has_policy:
        family = "knowledge_other"
    elif has_product:
        family = "catalog"
    elif has_off_topic:
        family = "off_topic"
    else:
        family = "unclear"
    debug = dict(understanding.debug or {})
    debug["llm_chat_surface_intent_family"] = family
    debug["llm_chat_surface_intent_confidence"] = understanding.intent_confidence
    debug["llm_chat_surface_intent_reason"] = understanding.reason
    debug["llm_chat_surface_intent_knowledge_query"] = knowledge_query
    return SurfaceIntentClassificationResult(
        intent_family=family,
        knowledge_query=knowledge_query,
        reason=str(understanding.reason or ""),
        confidence=float(understanding.intent_confidence or 0.0),
        store_overview_request=store_overview_request,
        llm_call_count=int(understanding.llm_call_count or 0),
        debug=debug,
    )


def _build_detail_inference_from_llm_data(
    *,
    llm_data: Mapping[str, Any] | None,
    allowed_exact_attributes: Sequence[str],
    allowed_soft_attributes: Sequence[str],
    attribute_value_candidates: Sequence[Mapping[str, Any]] | None = None,
    confidence: float,
    min_confidence: float,
    debug: Dict[str, Any],
) -> DetailQueryInferenceResult:
    requested_fields = _normalize_requested_fields((llm_data or {}).get("requested_fields"))
    attribute_filters = _normalize_candidate_filters(
        filters=(llm_data or {}).get("attribute_filters"),
        allowed_attributes=list(allowed_exact_attributes) + list(allowed_soft_attributes),
    )
    attribute_filters = _align_candidate_filter_values(
        filters=attribute_filters,
        attribute_value_candidates=attribute_value_candidates,
    )
    semantic_hints = _normalize_semantic_hints((llm_data or {}).get("semantic_hints"))
    unknown_terms = _normalize_unknown_terms((llm_data or {}).get("unknown_terms"))
    clarify_focus = normalize_focus_key((llm_data or {}).get("clarify_focus"))
    wants_image = bool((llm_data or {}).get("wants_image", False))

    debug["llm_detail_query_confidence"] = confidence
    debug["llm_detail_query_requested_fields"] = list(requested_fields)
    debug["llm_detail_query_attribute_keys"] = list(attribute_filters.keys())
    debug["llm_detail_query_semantic_hints"] = list(semantic_hints)
    debug["llm_detail_query_unknown_terms"] = list(unknown_terms)
    debug["llm_detail_query_clarify_focus"] = clarify_focus

    trusted_llm_output = confidence >= min_confidence
    if not trusted_llm_output:
        requested_fields = []
        attribute_filters = {}
        semantic_hints = []
        unknown_terms = []
        wants_image = False
        clarify_focus = clarify_focus or "detail_request_needs_specific_product"
    elif unknown_terms and not attribute_filters and not semantic_hints and not requested_fields and not wants_image:
        clarify_focus = clarify_focus or "detail_request_needs_specific_product"

    return DetailQueryInferenceResult(
        requested_fields=requested_fields,
        attribute_filters=attribute_filters,
        wants_image=wants_image,
        semantic_hints=semantic_hints,
        unknown_terms=unknown_terms,
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
    db: AsyncSession | None = None,
    searchable_attribute_names: Sequence[str] | None = None,
    searchable_attribute_metadata: Sequence[Mapping[str, Any]] | None = None,
) -> DetailQueryInferenceResult:
    clean_workflow = normalize_text(workflow)
    debug: Dict[str, Any] = {
        "llm_detail_query_enabled": bool(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_ENABLED", True)),
        "llm_detail_query_used": False,
        "llm_detail_query_confidence": 0.0,
        "llm_detail_query_requested_fields": [],
        "llm_detail_query_attribute_keys": [],
        "llm_detail_query_semantic_hints": [],
        "llm_detail_query_unknown_terms": [],
        "llm_detail_query_clarify_focus": "",
    }
    if clean_workflow != "catalog":
        return DetailQueryInferenceResult(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            semantic_hints=[],
            unknown_terms=[],
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
            unknown_terms=[],
            clarify_focus="",
            debug=debug,
        )

    searchable_names, searchable_metadata = await _resolve_searchable_attribute_context(
        db=db,
        searchable_attribute_names=searchable_attribute_names,
        searchable_attribute_metadata=searchable_attribute_metadata,
    )
    allowed_exact_attributes = _allowed_exact_attributes(parser_rules, searchable_names)
    allowed_soft_attributes = _allowed_soft_attributes(parser_rules, searchable_names)
    attribute_value_candidates = await _load_attribute_value_candidates(
        db=db,
        user_text=user_text,
        allowed_attributes=list(allowed_exact_attributes) + list(allowed_soft_attributes),
    )
    attribute_value_options = await _load_attribute_value_options(
        db=db,
        allowed_attributes=list(allowed_exact_attributes) + list(allowed_soft_attributes),
    )
    debug["catalog_searchable_attribute_names"] = list(searchable_names)
    debug["catalog_searchable_attribute_metadata"] = list(searchable_metadata)
    debug["catalog_allowed_exact_attributes"] = list(allowed_exact_attributes)
    debug["catalog_allowed_soft_attributes"] = list(allowed_soft_attributes)
    debug["catalog_attribute_value_candidate_count"] = len(attribute_value_candidates)
    debug["catalog_attribute_value_candidates"] = [
        {
            "attribute": str(item.get("attribute") or ""),
            "value": str(item.get("value") or ""),
            "product_count": int(item.get("product_count") or 0),
        }
        for item in attribute_value_candidates[:10]
    ]
    debug["catalog_attribute_value_options"] = [
        {
            "attribute": str(item.get("attribute") or ""),
            "value_count": int(item.get("value_count") or 0),
            "values": [
                {
                    "value": str(value.get("value") or ""),
                    "product_count": int(value.get("product_count") or 0),
                }
                for value in list(item.get("values") or [])[:8]
                if isinstance(value, Mapping)
            ],
        }
        for item in attribute_value_options[:12]
    ]
    model = str(
        getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MODEL", "")
        or getattr(settings, "NLU_MODEL", "gpt-5-mini")
    ).strip()
    max_tokens = _detail_query_max_tokens()
    min_confidence = float(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MIN_CONFIDENCE", 0.55))
    system_prompt = (
        "You interpret detail requests for a body jewelry ecommerce assistant. "
        "Return strict JSON with keys: requested_fields, attribute_filters, wants_image, semantic_hints, unknown_terms, clarify_focus, confidence. "
        "requested_fields must be an array using only fields from: price, stock, image, attributes, name, sku. "
        "attribute_filters must only contain supported product attributes and should preserve the user's meaning without code-side alias rewriting. "
        "Only use attributes listed in allowed_exact_attributes or allowed_soft_attributes; those are the DB-searchable attributes with product values. "
        "Use attribute_metadata to understand field behavior. "
        "For attributes marked is_multivalue, each value is an independent tag membership, not one combined classification string. "
        "When multiple tag memberships are needed for a multivalue attribute, return an array of individual tag values for that attribute. "
        "existing_filters are previous product-search filters from the same conversation. "
        "Use existing_filters only when the current query is clearly a follow-up, refinement, or pronoun reference to previous results. "
        "When using them, combine compatible existing filters with the current new filters; do not carry them into an unrelated new search. "
        "Use attribute_value_candidates as DB-backed product vocabulary. "
        "When the user's product wording matches or semantically normalizes to a candidate, copy that candidate's attribute and value exactly instead of splitting the phrase into smaller guessed filters. "
        "Use attribute_value_options as available DB values for low-cardinality attributes when candidates are sparse or the wording is indirect. "
        "If the user's wording clearly means one of those available options, copy that option's value exactly. "
        "Do not choose an option if none of the available values supports the user's meaning. "
        "For mixed product plus policy questions, extract only the product-shopping part into filters and semantic_hints; do not use policy/support words as catalog clarify_focus. "
        "Prefer the simplest DB candidate that represents the customer's product type. "
        "Avoid long category candidates with extra material, color, collection, or marketing qualifiers when the message asks for a broad type; use separate material or color filters for those words. "
        "If a value exists under both material and category, use the material attribute for material words such as gold, steel, titanium, acrylic, or silicone. "
        "Normalize customer wording to DB-backed values when the meaning is clear, including different word forms such as noun, adjective, singular, plural, or common ecommerce phrasing. "
        "Do not paraphrase, singularize, pluralize, or lowercase candidate values. "
        "Do not return singular/plural alternatives for the same concept; choose the strongest matching candidate value once. "
        "Example: if candidates contain category=Belly Bananas, do not output category=belly and design=banana. "
        "Generic browse requests such as find/show/buy products should leave requested_fields empty and wants_image false; "
        "only set requested_fields or wants_image when the user explicitly asks for a specific detail like price, stock, SKU, measurements, attributes, details, or pictures. "
        "If a product concept cannot be supported by any searchable attribute or DB-backed candidate value, put the concept in semantic_hints or clarify_focus instead of attribute_filters. "
        "If a word does not map to any supported attribute or DB-backed candidate value, put it in unknown_terms instead of filters. "
        "For gauge and measurement values, output the final product value directly. "
        "Examples: 25 gauge -> 25g, 1.5 inches -> 1.5inch, 8 mm -> 8mm. "
        "Do not rely on hardcoded synonym tables or alias rules. If a value is uncertain and no candidate supports it, keep it close to the user's wording instead of guessing a canonical form. "
        "semantic_hints must be up to 4 short concepts that should influence search but are not exact filters. "
        "unknown_terms must be up to 4 short unsupported terms that should not be turned into filters. "
        "If the request is ambiguous, set clarify_focus to a family key rather than a one-off term. "
        f"Supported ambiguity families: {', '.join(AMBIGUITY_FAMILY_KEYS)}. "
        "Use body_part when the body area or product anchor is unclear or unsafe to infer. "
        "If the request is unclear, set clarify_focus to detail_request_needs_specific_product. "
        "Do not invent unsupported fields or filters."
    )
    user_payload = {
        "query": str(user_text or ""),
        "workflow": clean_workflow,
        "existing_filters": dict(existing_filters or {}),
        "allowed_exact_attributes": list(allowed_exact_attributes),
        "allowed_soft_attributes": list(allowed_soft_attributes),
        "searchable_attributes": list(searchable_names),
        "attribute_metadata": list(searchable_metadata),
        "attribute_value_candidates": list(attribute_value_candidates),
        "attribute_value_options": list(attribute_value_options),
        "supported_ambiguity_families": list(AMBIGUITY_FAMILY_KEYS),
    }

    llm_call_count = 0
    confidence = 0.0
    requested_fields: List[str] = []
    attribute_filters: Dict[str, str] = {}
    semantic_hints: List[str] = []
    unknown_terms: List[str] = []
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
            reasoning_effort=_attribute_reasoning_effort(),
            timeout=_attribute_timeout_seconds(),
        )
        llm_call_count = 1
        debug["llm_detail_query_used"] = True
        try:
            confidence = float((llm_data or {}).get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        detail_result = _build_detail_inference_from_llm_data(
            llm_data=llm_data,
            allowed_exact_attributes=allowed_exact_attributes,
            allowed_soft_attributes=allowed_soft_attributes,
            attribute_value_candidates=attribute_value_candidates,
            confidence=confidence,
            min_confidence=min_confidence,
            debug=debug,
        )
        requested_fields = list(detail_result.requested_fields or [])
        attribute_filters = dict(detail_result.attribute_filters or {})
        semantic_hints = list(detail_result.semantic_hints or [])
        unknown_terms = list(detail_result.unknown_terms or [])
        clarify_focus = str(detail_result.clarify_focus or "")
        wants_image = bool(detail_result.wants_image)
    except Exception as exc:
        debug["llm_detail_query_error"] = str(exc)
        logger.warning("llm detail query inference failed: %s", exc)
        fallback_result = _fallback_detail_from_attribute_candidates(
            attribute_value_candidates=attribute_value_candidates,
            debug=debug,
            confidence=max(min_confidence, 0.8),
        )
        if fallback_result is not None:
            return fallback_result
        return DetailQueryInferenceResult(
            requested_fields=[],
            attribute_filters={},
            wants_image=False,
            semantic_hints=[],
            unknown_terms=[],
            clarify_focus="",
            confidence=0.0,
            llm_call_count=llm_call_count,
            debug=debug,
        )

    detail_result = DetailQueryInferenceResult(
        requested_fields=requested_fields,
        attribute_filters=attribute_filters,
        wants_image=wants_image,
        semantic_hints=semantic_hints,
        unknown_terms=unknown_terms,
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
    searchable_attribute_names, searchable_attribute_metadata = await _resolve_searchable_attribute_context(db=db)
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
        fallback = routing_policy._fallback_workflow_decision(reason="decision_engine_missing")
        execution_decision = routing_policy.ExecutionDecision(
            route_decision=fallback,
            execution_mode="component",
            reason="decision_engine_missing",
            feature_enabled=False,
            channel_allowed=False,
            tool_suitable=False,
            selection_source="decision_fallback",
        )

    has_product_signal = _understanding_hint_bool(understanding, "has_product_signal")
    has_product_detail_signal = _understanding_hint_bool(understanding, "has_product_detail_signal")
    if bool(getattr(execution_decision.route_decision, "needs_products", False)) or has_product_signal:
        detail = await infer_detail_query(
            user_text=user_text,
            workflow="catalog",
            alias_map=alias_map,
            parser_rules=parser_rules,
            existing_filters=existing_filters,
            searchable_attribute_names=searchable_attribute_names,
            searchable_attribute_metadata=searchable_attribute_metadata,
        )
        if has_product_detail_signal and not (detail.requested_fields or detail.wants_image):
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
            unknown_terms=[],
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
    max_tokens = max(240, int(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MAX_TOKENS", 60)))
    try:
        llm_data = await llm_service.generate_chat_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the catalog facet-list target for the user's question. "
                        "Return strict JSON with keys target and confidence. "
                        "A facet-list request asks for available option values, such as what materials, colors, gauges, or jewelry types are available. "
                        "If the user asks to see, show, find, buy, or browse products, return target as an empty string. "
                        "If the user describes a product condition or capability rather than asking for option values, return target as an empty string. "
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
            reasoning_effort=_attribute_reasoning_effort(),
            timeout=_attribute_timeout_seconds(),
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
    searchable_attribute_names: Sequence[str] | None = None,
    searchable_attribute_metadata: Sequence[Mapping[str, Any]] | None = None,
) -> AttributeExtractionResult:
    clean_workflow = normalize_text(workflow)
    searchable_names, searchable_metadata = await _resolve_searchable_attribute_context(
        db=db,
        searchable_attribute_names=searchable_attribute_names,
        searchable_attribute_metadata=searchable_attribute_metadata,
    )
    allowed_exact_attributes = _allowed_exact_attributes(parser_rules, searchable_names)
    allowed_soft_attributes = _allowed_soft_attributes(parser_rules, searchable_names)
    attribute_value_candidates = await _load_attribute_value_candidates(
        db=db,
        user_text=user_text,
        allowed_attributes=list(allowed_exact_attributes) + list(allowed_soft_attributes),
    )
    attribute_value_options = await _load_attribute_value_options(
        db=db,
        allowed_attributes=list(allowed_exact_attributes) + list(allowed_soft_attributes),
    )
    debug: Dict[str, Any] = {
        "llm_attribute_interpretation_enabled": bool(
            getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_ENABLED", True)
        ),
        "llm_attribute_interpretation_used": False,
        "llm_attribute_interpretation_confidence": 0.0,
        "llm_exact_filter_keys": [],
        "llm_soft_filter_keys": [],
        "semantic_hint_keys": [],
        "unknown_term_keys": [],
        "semantic_hint_clarify_focus": "",
        "semantic_hint_source": "",
        "catalog_searchable_attribute_names": list(searchable_names),
        "catalog_searchable_attribute_metadata": list(searchable_metadata),
        "catalog_allowed_exact_attributes": list(allowed_exact_attributes),
        "catalog_allowed_soft_attributes": list(allowed_soft_attributes),
        "catalog_attribute_value_candidate_count": len(attribute_value_candidates),
        "catalog_attribute_value_candidates": [
            {
                "attribute": str(item.get("attribute") or ""),
                "value": str(item.get("value") or ""),
                "product_count": int(item.get("product_count") or 0),
            }
            for item in attribute_value_candidates[:10]
        ],
        "catalog_attribute_value_options": [
            {
                "attribute": str(item.get("attribute") or ""),
                "value_count": int(item.get("value_count") or 0),
                "values": [
                    {
                        "value": str(value.get("value") or ""),
                        "product_count": int(value.get("product_count") or 0),
                    }
                    for value in list(item.get("values") or [])[:8]
                    if isinstance(value, Mapping)
                ],
            }
            for item in attribute_value_options[:12]
        ],
    }

    if clean_workflow != "catalog":
        return AttributeExtractionResult(
            exact_filters={},
            semantic_hints=[],
            unknown_terms=[],
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
            unknown_terms=[],
            soft_filters={},
            clarify_focus="",
            debug=debug,
        )

    model = str(
        getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MODEL", "")
        or getattr(settings, "NLU_MODEL", "gpt-5-mini")
    ).strip()
    max_tokens = max(900, int(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MAX_TOKENS", 220)))
    min_confidence = float(getattr(settings, "CHAT_ATTRIBUTE_INTERPRETATION_MIN_CONFIDENCE", 0.55))

    system_prompt = (
        "You interpret product-search intent for a body jewelry ecommerce assistant. "
        "Return strict JSON with keys: exact_filters, soft_filters, semantic_hints, unknown_terms, clarify_focus, confidence. "
        "When a concept is ambiguous, clarify_focus must be a family key rather than a one-off term. "
        f"Supported ambiguity families: {', '.join(AMBIGUITY_FAMILY_KEYS)}. "
        "Use body_part when the body area or product anchor is unclear or unsafe to infer. "
        "`exact_filters` must use only the provided allowed exact attributes for hard constraints. "
        "`soft_filters` must use only the provided allowed soft attributes for style or family cues. "
        "The allowed attributes are DB-searchable attributes with product values. "
        "Use attribute_metadata to understand field behavior. "
        "For attributes marked is_multivalue, each value is an independent tag membership, not one combined classification string. "
        "When multiple tag memberships are needed for a multivalue attribute, return an array of individual tag values for that attribute. "
        "Use attribute_value_candidates as DB-backed product vocabulary. "
        "When the user's product wording matches or semantically normalizes to a candidate, copy that candidate's attribute and value exactly. "
        "Use attribute_value_options as available DB values for low-cardinality attributes when candidates are sparse or the wording is indirect. "
        "If the user's wording clearly means one of those available options, copy that option's value exactly. "
        "Do not choose an option if none of the available values supports the user's meaning. "
        "For mixed product plus policy questions, extract only the product-shopping part into filters and semantic_hints; do not use policy/support words as catalog clarify_focus. "
        "Prefer the simplest DB candidate that represents the customer's product type. "
        "Avoid long category candidates with extra material, color, collection, or marketing qualifiers when the message asks for a broad type; use separate material or color filters for those words. "
        "If a value exists under both material and category, use the material attribute for material words such as gold, steel, titanium, acrylic, or silicone. "
        "Normalize customer wording to DB-backed values when the meaning is clear, including different word forms such as noun, adjective, singular, plural, or common ecommerce phrasing. "
        "If a concept cannot be supported by any searchable attribute or DB-backed candidate value, keep it in semantic_hints or clarify_focus instead of filters. "
        "If a word does not map to any supported attribute or DB-backed candidate value, keep it in unknown_terms instead of filters. "
        "Return filter values directly from the user's meaning without code-side alias rewriting. "
        "For gauge and measurement values, return the final product value directly. "
        "Examples: 25 gauge -> 25g, 1.5 inches -> 1.5inch, 8 mm -> 8mm. "
        "`semantic_hints` must be an array of up to 4 short concept strings for ambiguous or discovery-style concepts "
        "that should influence semantic search instead of structured filters. "
        "`unknown_terms` must be an array of up to 4 short unsupported terms that should not be turned into filters. "
        "Do not invent unsupported exact filters."
    )
    user_payload = {
        "query": str(user_text or ""),
        "workflow": clean_workflow,
        "existing_filters": dict(existing_filters or {}),
        "allowed_exact_attributes": list(allowed_exact_attributes),
        "allowed_soft_attributes": list(allowed_soft_attributes),
        "searchable_attributes": list(searchable_names),
        "attribute_metadata": list(searchable_metadata),
        "attribute_value_candidates": list(attribute_value_candidates),
        "attribute_value_options": list(attribute_value_options),
        "supported_ambiguity_families": list(AMBIGUITY_FAMILY_KEYS),
    }

    llm_call_count = 0
    llm_confidence = 0.0
    llm_exact_filters: Dict[str, str] = {}
    llm_soft_filters: Dict[str, str] = {}
    llm_semantic_hints: List[str] = []
    llm_unknown_terms: List[str] = []
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
            reasoning_effort=_attribute_reasoning_effort(),
            timeout=_attribute_timeout_seconds(),
        )
        llm_call_count = 1
        debug["llm_attribute_interpretation_used"] = True
        try:
            llm_confidence = float((llm_data or {}).get("confidence") or 0.0)
        except Exception:
            llm_confidence = 0.0
        llm_exact_filters = _normalize_candidate_filters(
            filters=(llm_data or {}).get("exact_filters"),
            allowed_attributes=allowed_exact_attributes,
        )
        llm_exact_filters = _align_candidate_filter_values(
            filters=llm_exact_filters,
            attribute_value_candidates=attribute_value_candidates,
        )
        llm_soft_filters = _normalize_candidate_filters(
            filters=(llm_data or {}).get("soft_filters"),
            allowed_attributes=allowed_soft_attributes,
        )
        llm_soft_filters = _align_candidate_filter_values(
            filters=llm_soft_filters,
            attribute_value_candidates=attribute_value_candidates,
        )
        llm_semantic_hints = _normalize_semantic_hints((llm_data or {}).get("semantic_hints"))
        llm_unknown_terms = _normalize_unknown_terms((llm_data or {}).get("unknown_terms"))
        llm_clarify_focus = normalize_focus_key((llm_data or {}).get("clarify_focus"))
    except Exception as exc:
        debug["llm_attribute_interpretation_error"] = str(exc)
        logger.warning("llm attribute interpretation failed: %s", exc)

    debug["llm_attribute_interpretation_confidence"] = llm_confidence
    trusted_llm_output = llm_confidence >= min_confidence

    validated_exact_filters: Dict[str, str] = dict(llm_exact_filters) if trusted_llm_output else {}
    soft_filters: Dict[str, str] = dict(llm_soft_filters) if trusted_llm_output else {}

    semantic_hints = list(llm_semantic_hints) if trusted_llm_output else []
    unknown_terms = list(llm_unknown_terms) if trusted_llm_output else []
    clarify_focus = str(llm_clarify_focus or "") if trusted_llm_output else ""

    debug["llm_exact_filter_keys"] = list(validated_exact_filters.keys())
    debug["llm_soft_filter_keys"] = list(soft_filters.keys())
    debug["semantic_hint_keys"] = list(semantic_hints)
    debug["unknown_term_keys"] = list(unknown_terms)
    debug["semantic_hint_clarify_focus"] = clarify_focus
    if semantic_hints:
        debug["semantic_hint_source"] = "llm"

    return AttributeExtractionResult(
        exact_filters=validated_exact_filters,
        semantic_hints=semantic_hints,
        unknown_terms=unknown_terms,
        soft_filters=soft_filters,
        clarify_focus=clarify_focus,
        confidence=llm_confidence if trusted_llm_output else 0.0,
        llm_call_count=llm_call_count,
        debug=debug,
    )
