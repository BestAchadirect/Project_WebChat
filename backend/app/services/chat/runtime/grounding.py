from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from app.schemas.chat import KnowledgeSource
from app.services.chat.retrieval.product_detail_resolver import ProductDetailResolver
from app.services.chat.runtime.search_plan import SearchPlan
from app.services.chat.text_normalization import normalize_user_text

GROUNDING_STATUSES = {"grounded", "weak", "unrelated", "needs_clarification"}


@dataclass(frozen=True)
class GroundingDecision:
    status: str
    workflow: str
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    allowed_product_ids: List[str] = field(default_factory=list)
    allowed_source_ids: List[str] = field(default_factory=list)
    missing_requirements: List[str] = field(default_factory=list)
    safe_customer_action: str = "fallback"
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_debug_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "workflow": self.workflow,
            "confidence": float(self.confidence),
            "reasons": list(self.reasons),
            "allowed_product_ids": list(self.allowed_product_ids),
            "allowed_source_ids": list(self.allowed_source_ids),
            "missing_requirements": list(self.missing_requirements),
            "safe_customer_action": self.safe_customer_action,
            "debug": dict(self.debug),
        }


def _card_identifier(card: Any) -> str:
    card_id = getattr(card, "id", None)
    if card_id is None:
        card_id = getattr(card, "product_id", None)
    return str(card_id or "").strip()


def _card_sku_values(card: Any) -> set[str]:
    values = {normalize_user_text(str(getattr(card, "sku", "") or ""))}
    for raw in list(getattr(card, "legacy_sku", []) or []):
        values.add(normalize_user_text(str(raw or "")))
    return {value for value in values if value}


def _semantic_text(card: Any) -> str:
    parts = [
        str(getattr(card, "name", "") or ""),
        str(getattr(card, "title", "") or ""),
        str(getattr(card, "description", "") or ""),
        str(getattr(card, "sku", "") or ""),
        str(getattr(card, "search_text", "") or ""),
    ]
    attrs = getattr(card, "attributes", {}) or {}
    if isinstance(attrs, dict):
        parts.extend(str(value or "") for value in attrs.values())
    return normalize_user_text(" ".join(parts))


def _matches_required_filters(card: Any, required_filters: Dict[str, str]) -> bool:
    for key, expected in dict(required_filters or {}).items():
        if not ProductDetailResolver._match_filter(card, key=key, expected=expected):
            return False
    return True


def _matches_sku(card: Any, sku_tokens: Sequence[str]) -> bool:
    expected = {normalize_user_text(str(token or "")) for token in list(sku_tokens or [])}
    expected = {value for value in expected if value}
    if not expected:
        return True
    return bool(expected.intersection(_card_sku_values(card)))


def _matches_semantic_terms(card: Any, semantic_terms: Sequence[str]) -> bool:
    terms = [normalize_user_text(term) for term in list(semantic_terms or []) if normalize_user_text(term)]
    if not terms:
        return True
    haystack = _semantic_text(card)
    return any(term in haystack for term in terms)


def evaluate_catalog_grounding(
    *,
    plan: SearchPlan,
    products: Sequence[Any],
    ambiguity_reason: str = "",
) -> GroundingDecision:
    workflow = str(plan.workflow or "catalog").strip().lower() or "catalog"
    cards = list(products or [])
    reasons: List[str] = []
    missing: List[str] = []

    if str(ambiguity_reason or "").strip():
        return GroundingDecision(
            status="needs_clarification",
            workflow=workflow,
            confidence=0.0,
            reasons=[str(ambiguity_reason or "retrieval_needs_clarification")],
            missing_requirements=[],
            safe_customer_action="clarify",
            debug={"candidate_product_count": len(cards)},
        )

    if not cards:
        reasons.append("no_retrieved_products")
        action = "no_match" if (plan.required_filters or plan.sku_tokens or plan.semantic_terms) else "clarify"
        return GroundingDecision(
            status="unrelated" if action == "no_match" else "needs_clarification",
            workflow=workflow,
            confidence=0.0,
            reasons=reasons,
            missing_requirements=list(plan.required_filters.keys()) + (["sku"] if plan.sku_tokens else []),
            safe_customer_action=action,
            debug={"candidate_product_count": 0},
        )

    allowed = list(cards)
    if plan.sku_tokens:
        sku_matches = [card for card in allowed if _matches_sku(card, plan.sku_tokens)]
        if not sku_matches:
            missing.append("sku")
            return GroundingDecision(
                status="unrelated",
                workflow=workflow,
                confidence=0.0,
                reasons=["sku_mismatch"],
                missing_requirements=missing,
                safe_customer_action="no_match",
                debug={"candidate_product_count": len(cards)},
            )
        allowed = sku_matches

    if plan.required_filters:
        filter_matches = [card for card in allowed if _matches_required_filters(card, plan.required_filters)]
        if not filter_matches:
            missing.extend(list(plan.required_filters.keys()))
            return GroundingDecision(
                status="unrelated",
                workflow=workflow,
                confidence=0.0,
                reasons=["required_filter_no_match"],
                missing_requirements=missing,
                safe_customer_action="no_match",
                debug={
                    "candidate_product_count": len(cards),
                    "required_filters": dict(plan.required_filters),
                },
            )
        if len(filter_matches) < len(allowed):
            reasons.append("filtered_unmatched_products")
        allowed = filter_matches

    if plan.semantic_terms and not (plan.required_filters or plan.sku_tokens):
        semantic_matches = [card for card in allowed if _matches_semantic_terms(card, plan.semantic_terms)]
        if not semantic_matches:
            return GroundingDecision(
                status="weak",
                workflow=workflow,
                confidence=0.35,
                reasons=["semantic_terms_not_confirmed"],
                allowed_product_ids=[_card_identifier(card) for card in allowed if _card_identifier(card)],
                missing_requirements=list(plan.semantic_terms),
                safe_customer_action="clarify",
                debug={"candidate_product_count": len(cards)},
            )
        allowed = semantic_matches

    confidence = 1.0
    if reasons:
        confidence = 0.85
    return GroundingDecision(
        status="grounded",
        workflow=workflow,
        confidence=confidence,
        reasons=reasons or ["evidence_matches_plan"],
        allowed_product_ids=[_card_identifier(card) for card in allowed if _card_identifier(card)],
        safe_customer_action="show_cards",
        debug={
            "candidate_product_count": len(cards),
            "grounded_product_count": len(allowed),
        },
    )


def evaluate_knowledge_grounding(
    *,
    plan: SearchPlan,
    sources: Sequence[KnowledgeSource],
    answer: str = "",
    min_relevance: float = 0.0,
    ambiguity_reason: str = "",
) -> GroundingDecision:
    workflow = str(plan.workflow or "knowledge").strip().lower() or "knowledge"
    source_list = list(sources or [])
    if str(ambiguity_reason or "").strip():
        return GroundingDecision(
            status="needs_clarification",
            workflow=workflow,
            confidence=0.0,
            reasons=[str(ambiguity_reason or "knowledge_needs_clarification")],
            safe_customer_action="clarify",
            debug={"candidate_source_count": len(source_list)},
        )
    if not source_list:
        return GroundingDecision(
            status="unrelated",
            workflow=workflow,
            confidence=0.0,
            reasons=["no_knowledge_sources"],
            safe_customer_action="clarify",
            debug={"candidate_source_count": 0},
        )

    top_relevance = max(
        (float(getattr(source, "relevance", 0.0) or 0.0) for source in source_list),
        default=0.0,
    )
    allowed = [
        source
        for source in source_list
        if float(getattr(source, "relevance", 0.0) or 0.0) >= float(min_relevance or 0.0)
    ]
    if not allowed:
        return GroundingDecision(
            status="weak",
            workflow=workflow,
            confidence=top_relevance,
            reasons=["knowledge_relevance_below_threshold"],
            allowed_source_ids=[
                str(source.source_id or "").strip()
                for source in source_list
                if str(source.source_id or "").strip()
            ],
            safe_customer_action="clarify",
            debug={
                "candidate_source_count": len(source_list),
                "top_relevance": top_relevance,
                "min_relevance": float(min_relevance or 0.0),
            },
        )
    if not str(answer or "").strip():
        return GroundingDecision(
            status="weak",
            workflow=workflow,
            confidence=top_relevance,
            reasons=["knowledge_sources_without_answer"],
            allowed_source_ids=[
                str(source.source_id or "").strip()
                for source in allowed
                if str(source.source_id or "").strip()
            ],
            safe_customer_action="clarify",
            debug={
                "candidate_source_count": len(source_list),
                "top_relevance": top_relevance,
                "min_relevance": float(min_relevance or 0.0),
            },
        )
    return GroundingDecision(
        status="grounded",
        workflow=workflow,
        confidence=top_relevance,
        reasons=["knowledge_sources_match_plan"],
        allowed_source_ids=[
            str(source.source_id or "").strip()
            for source in allowed
            if str(source.source_id or "").strip()
        ],
        safe_customer_action="answer",
        debug={
            "candidate_source_count": len(source_list),
            "grounded_source_count": len(allowed),
            "top_relevance": top_relevance,
            "min_relevance": float(min_relevance or 0.0),
        },
    )

