from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app.services.chat.components.types import ComponentSource
from app.services.chat.retrieval.result_policy import classify_match_tier


@dataclass(frozen=True)
class RetrievalOutcome:
    match_tier: str
    retrieval_source: ComponentSource
    product_count: int
    ambiguity_reason: str = ""

    @property
    def retrieval_quality(self) -> str:
        if self.is_exact_match:
            return "exact"
        if self.is_semantic_fallback:
            return "approximate"
        return "no_match"

    @property
    def is_exact_match(self) -> bool:
        return self.match_tier == "exact_match" and not self.needs_clarification

    @property
    def is_semantic_fallback(self) -> bool:
        return self.match_tier == "semantic_suggestion" and not self.needs_clarification

    @property
    def needs_clarification(self) -> bool:
        return bool(str(self.ambiguity_reason or "").strip())

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "match_tier": self.match_tier,
            "retrieval_source": self.retrieval_source.value,
            "product_count": int(self.product_count or 0),
            "ambiguity_reason": str(self.ambiguity_reason or ""),
            "is_exact_match": bool(self.is_exact_match),
            "is_semantic_fallback": bool(self.is_semantic_fallback),
            "needs_clarification": bool(self.needs_clarification),
            "retrieval_quality": self.retrieval_quality,
        }


def build_retrieval_outcome(
    *,
    retrieval_source: ComponentSource,
    product_ids: Sequence[Any],
    ambiguity_reason: str = "",
) -> RetrievalOutcome:
    structured_found = retrieval_source == ComponentSource.SQL and bool(list(product_ids or []))
    semantic_found = retrieval_source == ComponentSource.VECTOR and bool(list(product_ids or []))
    return RetrievalOutcome(
        match_tier=classify_match_tier(
            structured_found=structured_found,
            semantic_found=semantic_found,
        ),
        retrieval_source=retrieval_source,
        product_count=len(list(product_ids or [])),
        ambiguity_reason=str(ambiguity_reason or ""),
    )
