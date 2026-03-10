from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence


class MatchTier(str, Enum):
    EXACT_MATCH = "exact_match"
    SEMANTIC_SUGGESTION = "semantic_suggestion"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class SemanticFallbackDecision:
    allow: bool
    reason: str


def semantic_fallback_decision(
    *,
    intent: str,
    attribute_filters: Mapping[str, str],
    sku_tokens: Sequence[str],
    detail_mode: bool,
    compare_requested: bool,
    store_overview_request: bool,
) -> SemanticFallbackDecision:
    intent_norm = str(intent or "").strip().lower()
    if store_overview_request:
        return SemanticFallbackDecision(False, "store_overview_request")
    if compare_requested:
        return SemanticFallbackDecision(False, "compare_request")
    if detail_mode:
        return SemanticFallbackDecision(False, "detail_mode")
    if sku_tokens:
        return SemanticFallbackDecision(False, "sku_present")
    if dict(attribute_filters or {}):
        return SemanticFallbackDecision(False, "structured_filters_present")
    if intent_norm not in {"browse_products", "search_specific", "recommend_products"}:
        return SemanticFallbackDecision(False, "intent_not_product_discovery")
    return SemanticFallbackDecision(True, "discovery_query")


def classify_match_tier(*, structured_found: bool, semantic_found: bool) -> str:
    if structured_found:
        return MatchTier.EXACT_MATCH.value
    if semantic_found:
        return MatchTier.SEMANTIC_SUGGESTION.value
    return MatchTier.NO_MATCH.value
