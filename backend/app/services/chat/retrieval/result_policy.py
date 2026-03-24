from __future__ import annotations

from enum import Enum


class MatchTier(str, Enum):
    EXACT_MATCH = "exact_match"
    SEMANTIC_SUGGESTION = "semantic_suggestion"
    NO_MATCH = "no_match"


def classify_match_tier(*, structured_found: bool, semantic_found: bool) -> str:
    if structured_found:
        return MatchTier.EXACT_MATCH.value
    if semantic_found:
        return MatchTier.SEMANTIC_SUGGESTION.value
    return MatchTier.NO_MATCH.value
