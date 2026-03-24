from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.schemas.chat import KnowledgeSource
from app.services.chat.text_normalization import normalize_user_text
from app.services.chat.components.pipeline_runtime.state import PipelineExecutionState
from app.services.chat.components.types import ComponentType
from app.services.chat.retrieval.product_detail_resolver import ProductDetailResolver

class PipelineWorkflowPolicyMixin:
    @staticmethod
    def _build_execution_state(
            *,
            workflow: str,
            needs_products: bool,
            needs_knowledge: bool,
            needs_clarification: bool,
            route_override_used: bool,
            routing_selection_source: str,
            conversation_state_enabled: bool,
            conversation_state_filter_merge_applied: bool,
            debug_state_version: int,
            detail_requested_fields: Sequence[str],
            store_overview_request: bool,
        ) -> PipelineExecutionState:
            return PipelineExecutionState(
                debug_meta={
                    "component_pipeline_enabled": True,
                    "component_workflow": workflow,
                    "workflow_needs_products": bool(needs_products),
                    "workflow_needs_knowledge": bool(needs_knowledge),
                    "workflow_needs_clarification": bool(needs_clarification),
                    "path_kind": "component_pipeline",
                    "route_override_used": bool(route_override_used),
                    "routing_selection_source": str(routing_selection_source or "component_pipeline"),
                    "store_overview_request": store_overview_request,
                    "conversation_state_enabled": conversation_state_enabled,
                    "conversation_state_filter_merge_applied": bool(conversation_state_filter_merge_applied),
                    "conversation_state_loaded_version": int(debug_state_version),
                    "conversation_state_written": False,
                    "detail_requested_fields": list(detail_requested_fields or []),
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

    @classmethod
    def _contains_any_term(cls, *, text: str, terms: Sequence[str]) -> bool:
            normalized = normalize_user_text(text)
            return bool(normalized and any(term in normalized for term in terms))

    @staticmethod
    def _semantic_acceptance_score(best_distance: Optional[float]) -> float:
            if best_distance is None:
                return 0.0
            score = 1.0 - float(best_distance)
            return max(0.0, min(1.0, score))

    @classmethod
    def _apply_hard_constraint_gate(
            cls,
            *,
            cards: Sequence[Any],
            hard_filters: Dict[str, str],
        ) -> tuple[List[Any], Dict[str, Any]]:
            clean_hard_filters = {
                str(key).strip().lower(): str(value).strip()
                for key, value in dict(hard_filters or {}).items()
                if str(key).strip() and str(value).strip()
            }
            if not clean_hard_filters:
                return list(cards or []), {
                    "semantic_hard_constraint_keys": [],
                    "semantic_hard_constraint_count": 0,
                    "semantic_hard_constraint_match_count": len(list(cards or [])),
                    "semantic_hard_constraint_rejection_reason": "",
                }

            matched_cards: List[Any] = []
            for card in list(cards or []):
                matched = True
                for key, expected in clean_hard_filters.items():
                    if not ProductDetailResolver._match_filter(card, key=key, expected=expected):
                        matched = False
                        break
                if matched:
                    matched_cards.append(card)

            rejection_reason = ""
            if not matched_cards:
                rejection_reason = "hard_constraint_no_match"
            return matched_cards, {
                "semantic_hard_constraint_keys": list(clean_hard_filters.keys()),
                "semantic_hard_constraint_count": len(clean_hard_filters),
                "semantic_hard_constraint_match_count": len(matched_cards),
                "semantic_hard_constraint_rejection_reason": rejection_reason,
            }

    @classmethod
    def _apply_soft_hint_gate(
            cls,
            *,
            cards: Sequence[Any],
            soft_filters: Dict[str, str],
        ) -> tuple[List[Any], Dict[str, Any]]:
            clean_soft_filters = {
                str(key).strip().lower(): str(value).strip()
                for key, value in dict(soft_filters or {}).items()
                if str(key).strip() and str(value).strip()
            }
            if not clean_soft_filters:
                return list(cards or []), {
                    "semantic_soft_constraint_keys": [],
                    "semantic_soft_constraint_count": 0,
                    "semantic_soft_constraint_match_count": 0,
                    "semantic_soft_constraint_full_match_count": 0,
                    "semantic_soft_constraint_partial_match_count": 0,
                    "semantic_soft_constraint_rank_applied": False,
                    "semantic_soft_constraint_top_score": 0,
                    "semantic_soft_constraint_rejection_reason": "",
                }

            scored_cards: List[tuple[int, int, Any]] = []
            full_match_count = 0
            partial_match_count = 0
            for index, card in enumerate(list(cards or [])):
                match_count = sum(
                    1
                    for key, expected in clean_soft_filters.items()
                    if ProductDetailResolver._match_filter(card, key=key, expected=expected)
                )
                if match_count >= len(clean_soft_filters):
                    full_match_count += 1
                elif match_count > 0:
                    partial_match_count += 1
                scored_cards.append((match_count, index, card))

            scored_cards.sort(key=lambda item: (-item[0], item[1]))
            ranked_cards = [card for _score, _index, card in scored_cards]
            top_score = scored_cards[0][0] if scored_cards else 0
            return ranked_cards, {
                "semantic_soft_constraint_keys": list(clean_soft_filters.keys()),
                "semantic_soft_constraint_count": len(clean_soft_filters),
                "semantic_soft_constraint_match_count": full_match_count,
                "semantic_soft_constraint_full_match_count": full_match_count,
                "semantic_soft_constraint_partial_match_count": partial_match_count,
                "semantic_soft_constraint_rank_applied": bool(scored_cards),
                "semantic_soft_constraint_top_score": int(top_score),
                "semantic_soft_constraint_rejection_reason": "",
            }

    @staticmethod
    def _card_semantic_text(card: Any) -> str:
            parts: List[str] = [
                str(getattr(card, "name", "") or ""),
                str(getattr(card, "title", "") or ""),
                str(getattr(card, "description", "") or ""),
                str(getattr(card, "sku", "") or ""),
                str(getattr(card, "material", "") or ""),
                str(getattr(card, "search_text", "") or ""),
            ]
            attributes = getattr(card, "attributes", {}) or {}
            if isinstance(attributes, dict):
                parts.extend(str(value or "") for value in attributes.values())
            return normalize_user_text(" ".join(parts))

    @staticmethod
    def _semantic_hint_terms(hint: str) -> List[str]:
            normalized = normalize_user_text(hint)
            if not normalized:
                return []
            terms = [normalized]
            if normalized.startswith("steril"):
                terms.extend(
                    [
                        "steril",
                        "sterile",
                        "sterilized",
                        "sterilised",
                        "sterilization",
                        "sterilisation",
                    ]
                )
            deduped: List[str] = []
            seen: set[str] = set()
            for raw in terms:
                term = normalize_user_text(raw)
                if not term or term in seen:
                    continue
                seen.add(term)
                deduped.append(term)
            return deduped

    @classmethod
    def _apply_semantic_hint_rerank(
            cls,
            *,
            cards: Sequence[Any],
            semantic_hints: Sequence[str],
        ) -> tuple[List[Any], Dict[str, Any]]:
            clean_hints: List[str] = []
            seen_hints: set[str] = set()
            for raw in list(semantic_hints or []):
                hint = normalize_user_text(raw)
                if not hint or hint in seen_hints:
                    continue
                seen_hints.add(hint)
                clean_hints.append(hint)

            if not clean_hints:
                return list(cards or []), {
                    "semantic_hint_keys": [],
                    "semantic_hint_score": 0.0,
                    "semantic_hint_match_count": 0,
                    "semantic_hint_rank_applied": False,
                    "semantic_hint_rejection_reason": "",
                }

            scored_cards: List[tuple[float, int, Any]] = []
            match_count = 0
            for index, card in enumerate(list(cards or [])):
                haystack = cls._card_semantic_text(card)
                score = 0.0
                for hint in clean_hints:
                    terms = cls._semantic_hint_terms(hint)
                    if any(term and term in haystack for term in terms):
                        score += 1.0
                if score > 0:
                    match_count += 1
                scored_cards.append((score, index, card))

            scored_cards.sort(key=lambda item: (-item[0], item[1]))
            positive_cards = [card for score, _index, card in scored_cards if score > 0]
            ranked_cards = positive_cards or [card for _score, _index, card in scored_cards]
            top_score = float(scored_cards[0][0]) if scored_cards else 0.0
            normalized_score = top_score / max(1.0, float(len(clean_hints)))
            rejection_reason = ""
            if top_score <= 0:
                rejection_reason = "semantic_concept_unclear"

            return ranked_cards, {
                "semantic_hint_keys": list(clean_hints),
                "semantic_hint_score": round(normalized_score, 4),
                "semantic_hint_match_count": int(match_count),
                "semantic_hint_rank_applied": bool(scored_cards),
                "semantic_hint_rejection_reason": rejection_reason,
            }

    @classmethod
    def _is_high_risk_knowledge_request(cls, *, text: str) -> bool:
            return cls._contains_any_term(text=text, terms=cls._HIGH_RISK_KNOWLEDGE_TERMS)

    @staticmethod
    def _knowledge_sources_are_weak(*, sources: Sequence[KnowledgeSource], min_relevance: float) -> bool:
            if not sources:
                return True
            top_relevance = max(float(getattr(source, "relevance", 0.0) or 0.0) for source in list(sources or []))
            return top_relevance < float(min_relevance)

    @classmethod
    def _is_design_discovery_query(cls, *, user_text: str, attribute_filters: Dict[str, str]) -> bool:
            if dict(attribute_filters or {}):
                return False
            normalized = normalize_user_text(user_text)
            if not normalized:
                return False
            has_design_term = any(term in normalized for term in cls._DESIGN_DISCOVERY_TERMS)
            has_discovery_phrase = bool(
                re.search(r"\b(what|which|show|have|offer|carry|available)\b", normalized)
                or normalized.endswith("?")
            )
            return bool(has_design_term and has_discovery_phrase)

    @classmethod
    def _looks_like_gibberish(cls, *, user_text: str) -> bool:
            normalized = normalize_user_text(user_text)
            if not normalized:
                return True
            if any(hint in normalized for hint in cls._FALLBACK_VALID_HINTS):
                return False
            if re.search(r"(.)\1{4,}", normalized):
                return True
            alpha_tokens = re.findall(r"[a-z]+", normalized)
            if not alpha_tokens:
                return True
            if len(alpha_tokens) == 1:
                token = alpha_tokens[0]
                vowel_count = sum(1 for ch in token if ch in "aeiou")
                vowel_ratio = float(vowel_count) / max(1, len(token))
                if len(token) >= 8 and vowel_count <= 1:
                    return True
                if len(token) >= 8 and vowel_ratio <= 0.30:
                    return True
                if any(pattern in token for pattern in ("asdf", "qwer", "zxcv")):
                    return True
                if len(token) >= 8 and len(set(token)) <= 3:
                    return True
            return False

    @classmethod
    def _is_broad_discovery_request(
            cls,
            *,
            user_text: str,
            attribute_filters: Dict[str, str],
            sku_tokens: Sequence[str],
        ) -> bool:
            if dict(attribute_filters or {}) or list(sku_tokens or []):
                return False
            normalized = normalize_user_text(user_text)
            if not normalized:
                return False
            broad_terms = (
                "help",
                "something",
                "anything",
                "show me",
                "what do you have",
                "what can you show",
                "recommend",
                "suggest",
                "design",
                "style",
            )
            return any(term in normalized for term in broad_terms)

    @classmethod
    def _fallback_subtype(
            cls,
            *,
            user_text: str,
            route_reason: str,
            attribute_filters: Dict[str, str],
            sku_tokens: Sequence[str],
        ) -> str:
            if cls._looks_like_gibberish(user_text=user_text):
                return "fallback_gibberish"
            if cls._is_design_discovery_query(user_text=user_text, attribute_filters=attribute_filters):
                return "fallback_too_broad"
            if cls._is_broad_discovery_request(
                user_text=user_text,
                attribute_filters=attribute_filters,
                sku_tokens=sku_tokens,
            ):
                return "fallback_too_broad"
            normalized_reason = normalize_user_text(route_reason)
            if any(token in normalized_reason for token in ("timeout", "confidence", "invalid", "error", "unclear")):
                return "fallback_uncertain"
            return "fallback_uncertain"

    @classmethod
    def _plan_components(
            cls,
            *,
            user_text: str,
            workflow: str,
            product_count: int,
            is_detail_mode: bool,
            is_ambiguous: bool,
        ) -> List[ComponentType]:
            text = normalize_user_text(user_text)
            workflow_norm = normalize_user_text(workflow)

            if not text:
                return [ComponentType.ERROR]

            if is_ambiguous:
                return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]

            if workflow_norm in {"knowledge", "smalltalk"}:
                return [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]

            wants_reco = workflow_norm == "recommendation"

            components: List[ComponentType] = [ComponentType.QUERY_SUMMARY]

            if workflow_norm in {"catalog", "recommendation"} and product_count <= 0:
                return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
            if is_detail_mode:
                components.append(ComponentType.PRODUCT_DETAIL)
            else:
                components.append(ComponentType.PRODUCT_CARDS)

            if wants_reco:
                components.append(ComponentType.RECOMMENDATIONS)

            deduped: List[ComponentType] = []
            seen = set()
            for item in components:
                if item in seen:
                    continue
                seen.add(item)
                deduped.append(item)
            return deduped

    @classmethod
    def _detail_request_needs_specific_product(
            cls,
            *,
            requested_fields: Sequence[str],
            attribute_filters: Dict[str, str],
            match_count: int,
            has_exact_match: bool,
        ) -> bool:
            if has_exact_match or int(match_count) <= 1:
                return False
            fields = {
                str(item or "").strip().lower()
                for item in list(requested_fields or [])
                if str(item or "").strip()
            }
            if not fields.intersection(cls._DETAIL_CLARIFY_FIELDS):
                return False
            filter_keys = {
                str(key or "").strip().lower()
                for key, value in dict(attribute_filters or {}).items()
                if str(key or "").strip() and str(value or "").strip()
            }
            if not filter_keys:
                return True
            return filter_keys == {"jewelry_type"}
