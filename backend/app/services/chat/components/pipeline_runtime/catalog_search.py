from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings
from app.services.ai.llm_service import llm_service
from app.services.chat.retrieval import result_policy
from app.services.chat.parsing.search_policy import split_hard_and_soft_filters
from app.services.chat.components.cache import stable_cache_key
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.types import ComponentSource
from app.services.chat.retrieval.retrieval_outcome import build_retrieval_outcome
from app.services.chat.retrieval.product_detail_resolver import ProductDetailResolver
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.chat.text_normalization import normalize_user_text

logger = logging.getLogger(__name__)


class PipelineCatalogSearchMixin:
    @staticmethod
    def _supports_attribute_filter_pushdown(search_callable: Any) -> bool:
        if not callable(search_callable):
            return False
        try:
            signature = inspect.signature(search_callable)
        except (TypeError, ValueError):
            return False
        parameters = signature.parameters.values()
        return any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == "attribute_filters"
            for parameter in parameters
        )

    @staticmethod
    def _is_precision_retrieval_request(*, detail: Any, unique_sku_tokens: Sequence[str]) -> bool:
        if bool(unique_sku_tokens):
            return True
        if bool(getattr(detail, "is_detail_request", False)):
            return True
        requested_fields = {
            str(item or "").strip().lower()
            for item in list(getattr(detail, "requested_fields", []) or [])
            if str(item or "").strip()
        }
        return bool(requested_fields.intersection({"price", "stock", "image", "name", "sku"}))

    @classmethod
    def _should_allow_semantic_rescue(
        cls,
        *,
        workflow: str,
        detail: Any,
        unique_sku_tokens: Sequence[str],
    ) -> bool:
        if workflow != "catalog":
            return False
        return not cls._is_precision_retrieval_request(detail=detail, unique_sku_tokens=unique_sku_tokens)

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
                "hard_gate_removed_count": 0,
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
            "hard_gate_removed_count": max(0, len(list(cards or [])) - len(matched_cards)),
            "semantic_hard_constraint_rejection_reason": rejection_reason,
        }

    @classmethod
    def _apply_soft_hint_gate(
        cls,
        *,
        cards: Sequence[Any],
        soft_filters: Dict[str, str],
    ) -> tuple[List[Any], Dict[str, Any]]:
        ranked_cards, meta = cls._apply_preference_rerank(
            cards=cards,
            soft_filters=soft_filters,
            semantic_hints=[],
        )
        return ranked_cards, {
            "semantic_soft_constraint_keys": list(meta.get("semantic_soft_constraint_keys", []) or []),
            "semantic_soft_constraint_count": int(meta.get("semantic_soft_constraint_count", 0) or 0),
            "semantic_soft_constraint_match_count": int(meta.get("semantic_soft_constraint_match_count", 0) or 0),
            "semantic_soft_constraint_full_match_count": int(meta.get("semantic_soft_constraint_full_match_count", 0) or 0),
            "semantic_soft_constraint_partial_match_count": int(meta.get("semantic_soft_constraint_partial_match_count", 0) or 0),
            "semantic_soft_constraint_rank_applied": bool(meta.get("semantic_soft_constraint_rank_applied", False)),
            "semantic_soft_constraint_top_score": int(meta.get("semantic_soft_constraint_top_score", 0) or 0),
            "semantic_soft_constraint_rejection_reason": str(meta.get("semantic_soft_constraint_rejection_reason", "") or ""),
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

    @classmethod
    def _apply_semantic_hint_rerank(
        cls,
        *,
        cards: Sequence[Any],
        semantic_hints: Sequence[str],
    ) -> tuple[List[Any], Dict[str, Any]]:
        ranked_cards, meta = cls._apply_preference_rerank(
            cards=cards,
            soft_filters={},
            semantic_hints=semantic_hints,
        )
        return ranked_cards, {
            "semantic_hint_keys": list(meta.get("semantic_hint_keys", []) or []),
            "semantic_hint_score": float(meta.get("semantic_hint_score", 0.0) or 0.0),
            "semantic_hint_match_count": int(meta.get("semantic_hint_match_count", 0) or 0),
            "semantic_hint_rank_applied": bool(meta.get("semantic_hint_rank_applied", False)),
            "semantic_hint_rejection_reason": str(meta.get("semantic_hint_rejection_reason", "") or ""),
        }

    @classmethod
    def _apply_preference_rerank(
        cls,
        *,
        cards: Sequence[Any],
        soft_filters: Dict[str, str],
        semantic_hints: Sequence[str],
    ) -> tuple[List[Any], Dict[str, Any]]:
        clean_soft_filters = {
            str(key).strip().lower(): str(value).strip()
            for key, value in dict(soft_filters or {}).items()
            if str(key).strip() and str(value).strip()
        }
        clean_hints: List[str] = []
        seen_hints: set[str] = set()
        for raw in list(semantic_hints or []):
            hint = normalize_user_text(raw)
            if not hint or hint in seen_hints:
                continue
            seen_hints.add(hint)
            clean_hints.append(hint)

        if not clean_soft_filters and not clean_hints:
            return list(cards or []), {
                "semantic_soft_constraint_keys": [],
                "semantic_soft_constraint_count": 0,
                "semantic_soft_constraint_match_count": 0,
                "semantic_soft_constraint_full_match_count": 0,
                "semantic_soft_constraint_partial_match_count": 0,
                "semantic_soft_constraint_rank_applied": False,
                "semantic_soft_constraint_top_score": 0,
                "semantic_soft_constraint_rejection_reason": "",
                "semantic_hint_keys": [],
                "semantic_hint_score": 0.0,
                "semantic_hint_match_count": 0,
                "semantic_hint_rank_applied": False,
                "semantic_hint_rejection_reason": "",
                "semantic_preference_rerank_passes": 0,
            }

        scored_cards: List[tuple[int, float, int, Any]] = []
        full_match_count = 0
        partial_match_count = 0
        hint_match_count = 0
        for index, card in enumerate(list(cards or [])):
            soft_match_count = 0
            if clean_soft_filters:
                soft_match_count = sum(
                    1
                    for key, expected in clean_soft_filters.items()
                    if ProductDetailResolver._match_filter(card, key=key, expected=expected)
                )
                if soft_match_count >= len(clean_soft_filters):
                    full_match_count += 1
                elif soft_match_count > 0:
                    partial_match_count += 1

            hint_score = 0.0
            if clean_hints:
                haystack = cls._card_semantic_text(card)
                for hint in clean_hints:
                    if hint and hint in haystack:
                        hint_score += 1.0
                if hint_score > 0:
                    hint_match_count += 1

            scored_cards.append((soft_match_count, hint_score, index, card))

        scored_cards.sort(key=lambda item: (-item[0], -item[1], item[2]))
        ranked_cards = [card for _soft_score, _hint_score, _index, card in scored_cards]
        if clean_hints and hint_match_count > 0:
            ranked_cards = [
                card
                for _soft_score, hint_score, _index, card in scored_cards
                if hint_score > 0.0
            ]
        top_soft_score = scored_cards[0][0] if scored_cards else 0
        top_hint_score = float(scored_cards[0][1]) if scored_cards else 0.0
        hint_rejection_reason = ""
        if clean_hints and top_hint_score <= 0.0:
            hint_rejection_reason = "semantic_concept_unclear"

        return ranked_cards, {
            "semantic_soft_constraint_keys": list(clean_soft_filters.keys()),
            "semantic_soft_constraint_count": len(clean_soft_filters),
            "semantic_soft_constraint_match_count": full_match_count,
            "semantic_soft_constraint_full_match_count": full_match_count,
            "semantic_soft_constraint_partial_match_count": partial_match_count,
            "semantic_soft_constraint_rank_applied": bool(clean_soft_filters and scored_cards),
            "semantic_soft_constraint_top_score": int(top_soft_score),
            "semantic_soft_constraint_rejection_reason": "",
            "semantic_hint_keys": list(clean_hints),
            "semantic_hint_score": round(
                top_hint_score / max(1.0, float(len(clean_hints))) if clean_hints else 0.0,
                4,
            ),
            "semantic_hint_match_count": int(hint_match_count),
            "semantic_hint_rank_applied": bool(clean_hints and scored_cards),
            "semantic_hint_rejection_reason": hint_rejection_reason,
            "semantic_preference_rerank_passes": 1,
        }

    async def _run_catalog_retrieval_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            workflow: str,
            detail: Any,
            unique_sku_tokens: Sequence[str],
            result_fetch_limit: int,
            normalized_text: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> tuple[bool, List[Any], Optional[List[float]]]:
        capabilities = state.decision.runtime_capabilities or build_chat_runtime_capabilities()
        state.decision.runtime_capabilities = capabilities
        semantic_first_enabled = bool(capabilities.chat_semantic_first_enabled)
        debug_meta["semantic_first_enabled"] = semantic_first_enabled
        debug_meta["semantic_search_mode"] = "vector_first" if semantic_first_enabled else "semantic_disabled"
        if not semantic_first_enabled:
            return False, [], None

        plan = state.decision.search_plan
        plan_strictness = dict(getattr(plan, "strictness", {}) or {}) if plan is not None else {}
        hard_filters, soft_filters = split_hard_and_soft_filters(
            attribute_filters=dict(detail.attribute_filters or {}),
            strictness=plan_strictness,
        )
        semantic_hints = [
            str(item or "").strip()
            for item in list(getattr(detail, "semantic_hints", []) or [])
            if str(item or "").strip()
        ]
        clarify_focus = str(getattr(detail, "clarify_focus", "") or "").strip().lower()
        debug_meta["semantic_first_enabled"] = semantic_first_enabled
        debug_meta["semantic_search_mode"] = "vector_first" if semantic_first_enabled else "semantic_disabled"
        debug_meta["semantic_hard_constraint_keys"] = list(hard_filters.keys())
        debug_meta["semantic_soft_hint_keys"] = list(soft_filters.keys())
        debug_meta["semantic_hint_keys"] = list(semantic_hints)
        debug_meta["semantic_hint_clarify_focus"] = clarify_focus
        debug_meta["semantic_hint_clarify_used"] = False
        lexical_search_used = False
        lexical_rescue_used = False
        debug_meta["lexical_search_used"] = False
        debug_meta["lexical_rescue_used"] = False
        debug_meta["lexical_result_count"] = 0
        retrieval_query_text = str(getattr(plan, "semantic_query", "") or text or "").strip()
        state.catalog.query_cache_key = stable_cache_key(
            f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:query_ids",
            {
                "q": normalize_user_text(retrieval_query_text) or normalized_text,
                "locale": locale.lower(),
                "sku": unique_sku_tokens[0].lower() if unique_sku_tokens else "",
                "sku_list": [item.lower() for item in unique_sku_tokens[:5]],
                "filters": detail.attribute_filters,
                "semantic_hints": semantic_hints,
                "catalog_version": str(capabilities.chat_catalog_version),
                "search_mode": "vector_lexical_hybrid_v1",
                "presentation": "master_representative_v1",
                "fetch_limit": result_fetch_limit,
            },
        )
        debug_meta["catalog_query_cache_key"] = state.catalog.query_cache_key
        cached_ids_payload = await self._component_cache.get_json(state.catalog.query_cache_key)
        product_ids: List[Any] = []
        retrieval_source = ComponentSource.VECTOR
        query_embedding: Optional[List[float]] = None
        canonical_products: List[Any] = []
        semantic_cards: List[Any] = []
        semantic_best_distance: Optional[float] = None
        semantic_exact_lookup_used = False
        semantic_guardrail_used = False
        semantic_guardrail_reason = ""
        semantic_hard_constraint_rejection_reason = ""
        semantic_result_source = ComponentSource.VECTOR
        structured_first_hit = False
        allow_semantic_rescue = self._should_allow_semantic_rescue(
            workflow=workflow,
            detail=detail,
            unique_sku_tokens=unique_sku_tokens,
        )
        pushdown_hard_filters = dict(hard_filters or {}) if hard_filters and not allow_semantic_rescue else {}
        debug_meta["semantic_rescue_allowed"] = allow_semantic_rescue
        debug_meta["semantic_precision_request"] = not allow_semantic_rescue
        debug_meta["semantic_filter_pushdown_keys"] = list(pushdown_hard_filters.keys())
        embedding_error: Optional[str] = None
        if isinstance(cached_ids_payload, dict) and isinstance(cached_ids_payload.get("product_ids"), list):
            product_ids = list(cached_ids_payload.get("product_ids") or [])
            cached_source = str(cached_ids_payload.get("source") or "vector")
            retrieval_source = (
                ComponentSource(cached_source)
                if cached_source in {e.value for e in ComponentSource}
                else ComponentSource.VECTOR
            )
            state.retrieval.result_count = int(cached_ids_payload.get("result_count") or 0)
            debug_meta["semantic_acceptance_score"] = float(cached_ids_payload.get("semantic_acceptance_score") or 0.0)
            debug_meta["semantic_hint_score"] = float(cached_ids_payload.get("semantic_hint_score") or 0.0)
            debug_meta["semantic_guardrail_used"] = bool(cached_ids_payload.get("semantic_guardrail_used", False))
            debug_meta["semantic_guardrail_reason"] = str(cached_ids_payload.get("semantic_guardrail_reason") or "")
            debug_meta["lexical_search_used"] = bool(cached_ids_payload.get("lexical_search_used", False))
            debug_meta["lexical_rescue_used"] = bool(cached_ids_payload.get("lexical_rescue_used", False))
            debug_meta["semantic_hard_constraint_rejection_reason"] = str(
                cached_ids_payload.get("semantic_hard_constraint_rejection_reason") or ""
            )
            debug_meta["semantic_exact_lookup_used"] = bool(cached_ids_payload.get("semantic_exact_lookup_used", False))
            debug_meta["match_tier"] = result_policy.classify_match_tier(
                structured_found=retrieval_source == ComponentSource.SQL and bool(product_ids),
                semantic_found=retrieval_source == ComponentSource.VECTOR and bool(product_ids),
            )
        else:
            if workflow == "catalog" and (
                unique_sku_tokens
                or any(str(value or "").strip() for value in dict(detail.attribute_filters or {}).values())
            ):
                try:
                    structured_started = time.perf_counter()
                    structured_result, _structured_meta = await self._catalog_search.structured_search(
                        sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                        attribute_filters=dict(detail.attribute_filters or {}),
                        limit=result_fetch_limit,
                        candidate_cap=int(capabilities.chat_structured_candidate_cap),
                        catalog_version=str(capabilities.chat_catalog_version),
                        return_ids_only=True,
                    )
                    spans["db_product_lookup_ms"] += (time.perf_counter() - structured_started) * 1000.0
                    structured_ids = list(getattr(structured_result, "product_ids", None) or [])
                    debug_meta["semantic_structured_first_used"] = True
                    debug_meta["semantic_structured_first_hit"] = bool(structured_ids)
                    if structured_ids:
                        structured_first_hit = True
                        product_ids = structured_ids
                        state.catalog.product_ids = list(product_ids)
                        state.retrieval.result_count = len(product_ids)
                        retrieval_source = ComponentSource.SQL
                        semantic_result_source = ComponentSource.SQL
                        semantic_best_distance = 0.0
                        semantic_exact_lookup_used = bool(unique_sku_tokens)
                        semantic_guardrail_used = True
                        semantic_guardrail_reason = "structured_filter_lookup"
                except Exception as exc:
                    debug_meta["semantic_structured_first_error"] = str(exc)

            if not product_ids and int(capabilities.chat_hard_max_embeddings_per_request) > 0:
                retry_max = max(0, int(capabilities.chat_embedding_retry_max))
                for attempt in range(retry_max + 1):
                    try:
                        embed_started = time.perf_counter()
                        embedding = await llm_service.generate_embedding(retrieval_query_text or text)
                        spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                        query_embedding = list(embedding or [])
                        state.catalog.query_embedding = query_embedding
                        external_call_counts["embedding_query"] = int(external_call_counts.get("embedding_query", 0)) + 1
                        debug_meta["component_embedding_retry_count"] = attempt
                        break
                    except Exception as exc:
                        embedding_error = str(exc)
                        debug_meta["component_embedding_error"] = embedding_error
                        debug_meta["component_embedding_retry_count"] = attempt + 1
                        logger.warning(
                            "Chat query embedding failed on attempt %s/%s: %s",
                            attempt + 1,
                            retry_max + 1,
                            embedding_error,
                        )
                        if attempt >= retry_max:
                            break

            if query_embedding is None and (unique_sku_tokens or hard_filters):
                exact_started = time.perf_counter()
                exact_result, _exact_meta = await self._catalog_search.structured_search(
                    sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                    attribute_filters=hard_filters,
                    limit=result_fetch_limit,
                    candidate_cap=int(capabilities.chat_structured_candidate_cap),
                    catalog_version=str(capabilities.chat_catalog_version),
                    return_ids_only=True,
                )
                spans["db_product_lookup_ms"] += (time.perf_counter() - exact_started) * 1000.0
                product_ids = list(exact_result.product_ids or [])
                state.catalog.product_ids = list(product_ids)
                state.retrieval.result_count = len(product_ids)
                semantic_best_distance = 0.0 if product_ids else None
                semantic_exact_lookup_used = bool(unique_sku_tokens and product_ids)
                semantic_guardrail_used = True
                semantic_guardrail_reason = (
                    "exact_lookup_without_embedding"
                    if unique_sku_tokens
                    else "embedding_unavailable_structured_guardrail"
                )
                semantic_result_source = ComponentSource.SQL
                retrieval_source = ComponentSource.SQL
            elif unique_sku_tokens and query_embedding is not None:
                exact_started = time.perf_counter()
                exact_result = await self._catalog_search.smart_search(
                    query_embedding=query_embedding,
                    candidates=unique_sku_tokens,
                    limit=result_fetch_limit,
                )
                spans["vector_search_ms"] += (time.perf_counter() - exact_started) * 1000.0
                semantic_cards = list(exact_result.cards or [])
                exact_product_ids = getattr(exact_result, "product_ids", None)
                product_ids = list(exact_product_ids or [self._card_identifier(card) for card in semantic_cards])
                state.catalog.product_ids = list(product_ids)
                semantic_best_distance = getattr(exact_result, "best_distance", None)
                semantic_exact_lookup_used = bool(
                    semantic_best_distance is not None and float(semantic_best_distance) == 0.0
                )
                semantic_result_source = ComponentSource.SQL if semantic_exact_lookup_used else ComponentSource.VECTOR
                retrieval_source = semantic_result_source
            elif query_embedding is not None:
                vector_started = time.perf_counter()
                vector_kwargs = {
                    "query_embedding": query_embedding,
                    "limit": result_fetch_limit,
                    "candidate_limit": max(result_fetch_limit * 4, 36),
                }
                vector_search = getattr(self._catalog_search, "vector_search")
                if pushdown_hard_filters and self._supports_attribute_filter_pushdown(vector_search):
                    vector_kwargs["attribute_filters"] = pushdown_hard_filters
                vector_result = await vector_search(**vector_kwargs)
                spans["vector_search_ms"] += (time.perf_counter() - vector_started) * 1000.0
                semantic_cards = list(vector_result.cards or [])
                vector_product_ids = getattr(vector_result, "product_ids", None)
                product_ids = list(vector_product_ids or [self._card_identifier(card) for card in semantic_cards])
                state.catalog.product_ids = list(product_ids)
                semantic_best_distance = getattr(vector_result, "best_distance", None)
                vector_meta = dict(getattr(self._catalog_search, "last_meta", {}) or {})
                if "retrieval_filter_pushdown_keys" in vector_meta:
                    debug_meta["vector_filter_pushdown_keys"] = list(
                        vector_meta.get("retrieval_filter_pushdown_keys") or []
                    )
                    debug_meta["vector_filter_pushdown_count"] = int(
                        vector_meta.get("retrieval_filter_pushdown_count", 0) or 0
                    )
                    debug_meta["vector_filter_pushdown_slot_count"] = int(
                        vector_meta.get("retrieval_filter_pushdown_slot_count", 0) or 0
                    )
            else:
                product_ids = []
                state.catalog.product_ids = []

            structured_fallback_used = False
            if (
                not product_ids
                and not state.decision.ambiguity_reason
                and workflow == "catalog"
                and (unique_sku_tokens or any(str(value or "").strip() for value in dict(detail.attribute_filters or {}).values()))
            ):
                try:
                    fallback_started = time.perf_counter()
                    fallback_result, _fallback_meta = await self._catalog_search.structured_search(
                        sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                        attribute_filters=dict(detail.attribute_filters or {}),
                        limit=result_fetch_limit,
                        candidate_cap=int(capabilities.chat_structured_candidate_cap),
                        catalog_version=str(capabilities.chat_catalog_version),
                        return_ids_only=True,
                    )
                    spans["db_product_lookup_ms"] += (time.perf_counter() - fallback_started) * 1000.0
                    fallback_ids = list(getattr(fallback_result, "product_ids", None) or [])
                    if fallback_ids:
                        product_ids = fallback_ids
                        state.catalog.product_ids = list(product_ids)
                        state.retrieval.result_count = len(product_ids)
                        retrieval_source = ComponentSource.SQL
                        semantic_result_source = ComponentSource.SQL
                        semantic_best_distance = 0.0
                        structured_fallback_used = True
                        debug_meta["semantic_structured_fallback_used"] = True
                except Exception as exc:
                    debug_meta["semantic_structured_fallback_error"] = str(exc)

            if semantic_cards and hard_filters:
                filtered_cards, hard_meta = self._apply_hard_constraint_gate(
                    cards=semantic_cards,
                    hard_filters=hard_filters,
                )
                debug_meta.update(hard_meta)
                if filtered_cards:
                    semantic_cards = filtered_cards
                    product_ids = [self._card_identifier(card) for card in semantic_cards]
                    state.catalog.product_ids = list(product_ids)
                else:
                    semantic_guardrail_used = True
                    semantic_guardrail_reason = "hard_constraint_verification"
                    semantic_hard_constraint_rejection_reason = (
                        hard_meta.get("semantic_hard_constraint_rejection_reason") or "hard_constraint_no_match"
                    )
                    debug_meta["semantic_hard_constraint_rejection_reason"] = semantic_hard_constraint_rejection_reason
                    if allow_semantic_rescue:
                        debug_meta["semantic_approximate_rescue_used"] = True
                        debug_meta["semantic_rescue_reason"] = "hard_constraint_relaxed"
                        semantic_guardrail_reason = "hard_constraint_relaxed"
                        debug_meta["semantic_guardrail_reason"] = semantic_guardrail_reason
                        if semantic_cards:
                            product_ids = [self._card_identifier(card) for card in semantic_cards]
                            state.catalog.product_ids = list(product_ids)
                            state.retrieval.result_count = len(product_ids)
                            semantic_result_source = ComponentSource.VECTOR
                            retrieval_source = ComponentSource.VECTOR if retrieval_source != ComponentSource.SQL else retrieval_source
                            logger.debug(
                                "Chat semantic hard constraint relaxed for broad request with filters=%s",
                                list(hard_filters.keys()),
                            )
                    else:
                        verify_started = time.perf_counter()
                        verify_result, _verify_meta = await self._catalog_search.structured_search(
                            sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                            attribute_filters=hard_filters,
                            limit=result_fetch_limit,
                            candidate_cap=int(capabilities.chat_structured_candidate_cap),
                            catalog_version=str(capabilities.chat_catalog_version),
                            return_ids_only=True,
                        )
                        spans["db_product_lookup_ms"] += (time.perf_counter() - verify_started) * 1000.0
                        verified_ids = list(verify_result.product_ids or [])
                        debug_meta["semantic_guardrail_verification_hit"] = bool(verified_ids)
                        debug_meta["semantic_guardrail_reason"] = semantic_guardrail_reason
                        if verified_ids:
                            product_ids = verified_ids
                            state.catalog.product_ids = list(product_ids)
                            semantic_cards = []
                            semantic_result_source = ComponentSource.SQL
                            retrieval_source = ComponentSource.SQL
                            semantic_best_distance = 0.0
                            logger.debug(
                                "Chat semantic hard constraint verification promoted structured results for filters=%s",
                                list(hard_filters.keys()),
                            )
                        else:
                            product_ids = []
                            state.catalog.product_ids = []
                            semantic_cards = []
                            state.retrieval.result_count = 0
                            state.decision.ambiguity_reason = "structured_no_match"
                            debug_meta["match_tier"] = result_policy.classify_match_tier(
                                structured_found=False,
                                semantic_found=False,
                            )
                            logger.debug(
                                "Chat semantic hard constraint verification found no structured matches for filters=%s",
                                list(hard_filters.keys()),
                            )

            soft_rerank_enabled = bool(capabilities.chat_semantic_soft_filter_rerank_enabled)
            lexical_search = getattr(self._catalog_search, "lexical_search", None)
            if callable(lexical_search) and workflow == "catalog":
                should_run_lexical = bool(
                    not structured_first_hit
                    and (semantic_hints or not product_ids or (allow_semantic_rescue and hard_filters))
                )
                if should_run_lexical:
                    try:
                        had_vector_candidates = bool(semantic_cards or product_ids)
                        lexical_started = time.perf_counter()
                        lexical_kwargs = {
                            "query_text": retrieval_query_text or text,
                            "limit": result_fetch_limit,
                            "candidate_limit": max(result_fetch_limit * 4, 36),
                        }
                        if pushdown_hard_filters and self._supports_attribute_filter_pushdown(lexical_search):
                            lexical_kwargs["attribute_filters"] = pushdown_hard_filters
                        lexical_result = await lexical_search(**lexical_kwargs)
                        spans["db_product_lookup_ms"] += (time.perf_counter() - lexical_started) * 1000.0
                        lexical_cards = list(getattr(lexical_result, "cards", None) or [])
                        lexical_search_used = True
                        debug_meta["lexical_search_used"] = True
                        debug_meta["lexical_result_count"] = len(lexical_cards)
                        lexical_meta = dict(getattr(self._catalog_search, "last_meta", {}) or {})
                        if "retrieval_filter_pushdown_keys" in lexical_meta:
                            debug_meta["lexical_filter_pushdown_keys"] = list(
                                lexical_meta.get("retrieval_filter_pushdown_keys") or []
                            )
                            debug_meta["lexical_filter_pushdown_count"] = int(
                                lexical_meta.get("retrieval_filter_pushdown_count", 0) or 0
                            )
                            debug_meta["lexical_filter_pushdown_slot_count"] = int(
                                lexical_meta.get("retrieval_filter_pushdown_slot_count", 0) or 0
                            )
                        if lexical_cards:
                            merged_cards: List[Any] = []
                            seen_ids: set[str] = set()
                            for card in list(lexical_cards) + list(semantic_cards or []):
                                card_id = self._card_identifier(card)
                                if not card_id or card_id in seen_ids:
                                    continue
                                seen_ids.add(card_id)
                                merged_cards.append(card)
                            semantic_cards = merged_cards
                            product_ids = [self._card_identifier(card) for card in semantic_cards]
                            state.catalog.product_ids = list(product_ids)
                            if not had_vector_candidates:
                                retrieval_source = ComponentSource.SQL
                                semantic_result_source = ComponentSource.SQL
                            if not state.retrieval.result_count:
                                state.retrieval.result_count = len(product_ids)
                            if not debug_meta.get("semantic_result_source"):
                                debug_meta["semantic_result_source"] = retrieval_source.value
                    except Exception as exc:
                        debug_meta["lexical_search_error"] = str(exc)

            should_rerank_preferences = bool(
                semantic_cards and ((soft_filters and soft_rerank_enabled) or semantic_hints)
            )
            if should_rerank_preferences:
                semantic_cards, preference_meta = self._apply_preference_rerank(
                    cards=semantic_cards,
                    soft_filters=soft_filters if soft_rerank_enabled else {},
                    semantic_hints=semantic_hints,
                )
                debug_meta.update(preference_meta)
                product_ids = [self._card_identifier(card) for card in semantic_cards]
                state.catalog.product_ids = list(product_ids)
                if preference_meta.get("semantic_soft_constraint_rank_applied"):
                    semantic_guardrail_used = True
                    semantic_guardrail_reason = "soft_constraint_rerank"
                    logger.debug(
                        "Chat semantic soft rerank applied for filters=%s full_matches=%s partial_matches=%s",
                        list(soft_filters.keys()),
                        int(preference_meta.get("semantic_soft_constraint_full_match_count", 0) or 0),
                        int(preference_meta.get("semantic_soft_constraint_partial_match_count", 0) or 0),
                    )
                if preference_meta.get("semantic_hint_rank_applied"):
                    semantic_guardrail_used = True
                if float(preference_meta.get("semantic_hint_score", 0.0) or 0.0) > 0.0 and lexical_search_used:
                    lexical_rescue_used = True
                    debug_meta["lexical_rescue_used"] = True
                    debug_meta["semantic_search_mode"] = "vector_lexical_hybrid"
                if (
                    semantic_hints
                    and float(preference_meta.get("semantic_hint_score", 0.0) or 0.0) <= 0.0
                    and not dict(getattr(detail, "attribute_filters", {}) or {})
                ):
                    semantic_guardrail_reason = "semantic_hint_clarify"
                    product_ids = []
                    state.catalog.product_ids = []
                    semantic_cards = []
                    state.retrieval.result_count = 0
                    state.decision.ambiguity_reason = "semantic_concept_unclear"
                    debug_meta["semantic_hint_clarify_used"] = True
                    debug_meta["match_tier"] = result_policy.classify_match_tier(
                        structured_found=False,
                        semantic_found=False,
                    )
                    logger.debug(
                        "Chat semantic hint clarify triggered for hints=%s focus=%s",
                        list(semantic_hints),
                        clarify_focus,
                    )

            if not product_ids and not state.decision.ambiguity_reason:
                if (
                    semantic_hints
                    and not hard_filters
                    and not dict(getattr(detail, "attribute_filters", {}) or {})
                ):
                    semantic_guardrail_used = True
                    semantic_guardrail_reason = semantic_guardrail_reason or "semantic_hint_clarify"
                    state.decision.ambiguity_reason = "semantic_concept_unclear"
                    debug_meta["semantic_hint_score"] = float(debug_meta.get("semantic_hint_score") or 0.0)
                    debug_meta["semantic_hint_clarify_used"] = True
                elif hard_filters:
                    state.decision.ambiguity_reason = "structured_no_match"
                    retrieval_source = ComponentSource.SQL
                    semantic_result_source = ComponentSource.SQL
                    if not debug_meta.get("semantic_hard_constraint_rejection_reason"):
                        debug_meta["semantic_hard_constraint_rejection_reason"] = "hard_constraint_no_match"
                elif dict(getattr(detail, "attribute_filters", {}) or {}):
                    state.decision.ambiguity_reason = "structured_no_match"
                    retrieval_source = ComponentSource.SQL
                    semantic_result_source = ComponentSource.SQL
                else:
                    state.decision.ambiguity_reason = "structured_no_match"

        state.catalog.query_product_ids = list(product_ids)
        debug_meta["catalog_query_product_ids"] = list(product_ids)
        if state.catalog.query_cache_key and product_ids:
            await self._component_cache.set_json(
                state.catalog.query_cache_key,
                {
                    "product_ids": [str(item) for item in product_ids],
                    "source": semantic_result_source.value,
                    "result_count": len(product_ids),
                    "semantic_acceptance_score": round(
                        self._semantic_acceptance_score(semantic_best_distance),
                        4,
                    ),
                    "semantic_hint_score": round(float(debug_meta.get("semantic_hint_score") or 0.0), 4),
                    "semantic_guardrail_used": semantic_guardrail_used,
                    "semantic_guardrail_reason": semantic_guardrail_reason,
                    "lexical_search_used": lexical_search_used,
                    "lexical_rescue_used": lexical_rescue_used,
                    "semantic_hard_constraint_rejection_reason": debug_meta.get(
                        "semantic_hard_constraint_rejection_reason", ""
                    ),
                    "semantic_exact_lookup_used": semantic_exact_lookup_used,
                },
                ttl_seconds=300,
            )
        state.retrieval.result_count = len(product_ids)
        state.retrieval.source = retrieval_source
        state.retrieval.outcome = build_retrieval_outcome(
            retrieval_source=retrieval_source,
            product_ids=product_ids,
            ambiguity_reason=str(state.decision.ambiguity_reason or ""),
        )
        debug_meta["semantic_acceptance_score"] = round(
            self._semantic_acceptance_score(semantic_best_distance),
            4,
        )
        debug_meta["semantic_guardrail_used"] = semantic_guardrail_used
        debug_meta["semantic_guardrail_reason"] = semantic_guardrail_reason
        debug_meta["semantic_exact_lookup_used"] = semantic_exact_lookup_used
        debug_meta["semantic_search_error"] = embedding_error or ""
        debug_meta["semantic_result_source"] = retrieval_source.value
        debug_meta["retrieval_source"] = retrieval_source.value
        debug_meta["match_tier"] = state.retrieval.outcome.match_tier
        debug_meta["retrieval_quality"] = state.retrieval.outcome.retrieval_quality
        debug_meta["retrieval_outcome"] = state.retrieval.outcome.to_debug_dict()
        state.catalog.semantic_search_done = True


        return True, product_ids, query_embedding

