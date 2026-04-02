from __future__ import annotations

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
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities

logger = logging.getLogger(__name__)


class PipelineCatalogSearchMixin:
    async def _run_catalog_retrieval_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            workflow: str,
            detail: Any,
            unique_sku_tokens: Sequence[str],
            recommendation_requested: bool,
            result_fetch_limit: int,
            normalized_text: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> tuple[bool, List[Any], Optional[List[float]]]:
        capabilities = state.runtime_capabilities or build_chat_runtime_capabilities()
        state.runtime_capabilities = capabilities
        semantic_first_enabled = bool(capabilities.chat_semantic_first_enabled)
        debug_meta["semantic_first_enabled"] = semantic_first_enabled
        debug_meta["semantic_search_mode"] = "vector_first" if semantic_first_enabled else "semantic_disabled"
        if not semantic_first_enabled:
            return False, [], None

        hard_filters, soft_filters = split_hard_and_soft_filters(
            attribute_filters=dict(detail.attribute_filters or {}),
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
        state.query_cache_key = stable_cache_key(
            f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:query_ids",
            {
                "q": normalized_text,
                "locale": locale.lower(),
                "sku": unique_sku_tokens[0].lower() if unique_sku_tokens else "",
                "sku_list": [item.lower() for item in unique_sku_tokens[:5]],
                "filters": detail.attribute_filters,
                "semantic_hints": semantic_hints,
                "catalog_version": str(capabilities.chat_catalog_version),
                "search_mode": "vector_lexical_hybrid_v1",
                "presentation": "master_dedupe_v1",
                "fetch_limit": result_fetch_limit,
            },
        )
        debug_meta["catalog_query_cache_key"] = state.query_cache_key
        cached_ids_payload = await self._component_cache.get_json(state.query_cache_key)
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
        if isinstance(cached_ids_payload, dict) and isinstance(cached_ids_payload.get("product_ids"), list):
            product_ids = list(cached_ids_payload.get("product_ids") or [])
            cached_source = str(cached_ids_payload.get("source") or "vector")
            retrieval_source = (
                ComponentSource(cached_source)
                if cached_source in {e.value for e in ComponentSource}
                else ComponentSource.VECTOR
            )
            state.result_count = int(cached_ids_payload.get("result_count") or 0)
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
            embedding_error: Optional[str] = None
            if int(capabilities.chat_hard_max_embeddings_per_request) > 0:
                retry_max = max(0, int(capabilities.chat_embedding_retry_max))
                for attempt in range(retry_max + 1):
                    try:
                        embed_started = time.perf_counter()
                        embedding = await llm_service.generate_embedding(text)
                        spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                        query_embedding = list(embedding or [])
                        state.query_embedding = query_embedding
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
                state.product_ids = list(product_ids)
                state.result_count = len(product_ids)
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
                state.product_ids = list(product_ids)
                semantic_best_distance = getattr(exact_result, "best_distance", None)
                semantic_exact_lookup_used = bool(
                    semantic_best_distance is not None and float(semantic_best_distance) == 0.0
                )
                semantic_result_source = ComponentSource.SQL if semantic_exact_lookup_used else ComponentSource.VECTOR
                retrieval_source = semantic_result_source
            elif query_embedding is not None:
                vector_started = time.perf_counter()
                vector_result = await self._catalog_search.vector_search(
                    query_embedding=query_embedding,
                    limit=result_fetch_limit,
                    candidate_limit=max(result_fetch_limit * 4, 36),
                )
                spans["vector_search_ms"] += (time.perf_counter() - vector_started) * 1000.0
                semantic_cards = list(vector_result.cards or [])
                vector_product_ids = getattr(vector_result, "product_ids", None)
                product_ids = list(vector_product_ids or [self._card_identifier(card) for card in semantic_cards])
                state.product_ids = list(product_ids)
                semantic_best_distance = getattr(vector_result, "best_distance", None)
            else:
                product_ids = []
                state.product_ids = []

            structured_fallback_used = False
            if (
                not product_ids
                and not state.ambiguity_reason
                and workflow in {"catalog", "recommendation"}
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
                        state.product_ids = list(product_ids)
                        state.result_count = len(product_ids)
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
                    state.product_ids = list(product_ids)
                else:
                    semantic_guardrail_used = True
                    semantic_guardrail_reason = "hard_constraint_verification"
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
                    semantic_hard_constraint_rejection_reason = (
                        hard_meta.get("semantic_hard_constraint_rejection_reason") or "hard_constraint_no_match"
                    )
                    debug_meta["semantic_hard_constraint_rejection_reason"] = semantic_hard_constraint_rejection_reason
                    if verified_ids:
                        product_ids = verified_ids
                        state.product_ids = list(product_ids)
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
                        state.product_ids = []
                        semantic_cards = []
                        state.result_count = 0
                        state.ambiguity_reason = "structured_no_match"
                        debug_meta["match_tier"] = result_policy.classify_match_tier(
                            structured_found=False,
                            semantic_found=False,
                        )
                        logger.debug(
                            "Chat semantic hard constraint verification found no structured matches for filters=%s",
                            list(hard_filters.keys()),
                        )

            soft_rerank_enabled = bool(capabilities.chat_semantic_soft_filter_rerank_enabled)
            if semantic_cards and soft_filters and soft_rerank_enabled and not recommendation_requested:
                semantic_cards, soft_meta = self._apply_soft_hint_gate(
                    cards=semantic_cards,
                    soft_filters=soft_filters,
                )
                debug_meta.update(soft_meta)
                product_ids = [self._card_identifier(card) for card in semantic_cards]
                state.product_ids = list(product_ids)
                if soft_meta.get("semantic_soft_constraint_rank_applied"):
                    semantic_guardrail_used = True
                    semantic_guardrail_reason = "soft_constraint_rerank"
                    logger.debug(
                        "Chat semantic soft rerank applied for filters=%s full_matches=%s partial_matches=%s",
                        list(soft_filters.keys()),
                        int(soft_meta.get("semantic_soft_constraint_full_match_count", 0) or 0),
                        int(soft_meta.get("semantic_soft_constraint_partial_match_count", 0) or 0),
                    )

            lexical_search = getattr(self._catalog_search, "lexical_search", None)
            if callable(lexical_search) and not hard_filters and workflow in {"catalog", "recommendation"}:
                should_run_lexical = bool(semantic_hints or not product_ids)
                if should_run_lexical:
                    try:
                        had_vector_candidates = bool(semantic_cards or product_ids)
                        lexical_started = time.perf_counter()
                        lexical_result = await lexical_search(
                            query_text=text,
                            limit=result_fetch_limit,
                            candidate_limit=max(result_fetch_limit * 4, 36),
                        )
                        spans["db_product_lookup_ms"] += (time.perf_counter() - lexical_started) * 1000.0
                        lexical_cards = list(getattr(lexical_result, "cards", None) or [])
                        lexical_search_used = True
                        debug_meta["lexical_search_used"] = True
                        debug_meta["lexical_result_count"] = len(lexical_cards)
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
                            state.product_ids = list(product_ids)
                            if not had_vector_candidates:
                                retrieval_source = ComponentSource.SQL
                                semantic_result_source = ComponentSource.SQL
                            if not state.result_count:
                                state.result_count = len(product_ids)
                            if not debug_meta.get("semantic_result_source"):
                                debug_meta["semantic_result_source"] = retrieval_source.value
                    except Exception as exc:
                        debug_meta["lexical_search_error"] = str(exc)

            if semantic_cards and semantic_hints:
                semantic_cards, semantic_hint_meta = self._apply_semantic_hint_rerank(
                    cards=semantic_cards,
                    semantic_hints=semantic_hints,
                )
                debug_meta.update(semantic_hint_meta)
                product_ids = [self._card_identifier(card) for card in semantic_cards]
                state.product_ids = list(product_ids)
                if semantic_hint_meta.get("semantic_hint_rank_applied"):
                    semantic_guardrail_used = True
                if float(semantic_hint_meta.get("semantic_hint_score", 0.0) or 0.0) > 0.0 and lexical_search_used:
                    lexical_rescue_used = True
                    debug_meta["lexical_rescue_used"] = True
                    debug_meta["semantic_search_mode"] = "vector_lexical_hybrid"
                if float(semantic_hint_meta.get("semantic_hint_score", 0.0) or 0.0) <= 0.0:
                    semantic_guardrail_reason = "semantic_hint_clarify"
                    product_ids = []
                    state.product_ids = []
                    semantic_cards = []
                    state.result_count = 0
                    state.ambiguity_reason = "semantic_concept_unclear"
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

            if not product_ids and not state.ambiguity_reason:
                if semantic_hints and not hard_filters:
                    semantic_guardrail_used = True
                    semantic_guardrail_reason = semantic_guardrail_reason or "semantic_hint_clarify"
                    state.ambiguity_reason = "semantic_concept_unclear"
                    debug_meta["semantic_hint_score"] = float(debug_meta.get("semantic_hint_score") or 0.0)
                    debug_meta["semantic_hint_clarify_used"] = True
                elif hard_filters:
                    state.ambiguity_reason = "structured_no_match"
                    if not debug_meta.get("semantic_hard_constraint_rejection_reason"):
                        debug_meta["semantic_hard_constraint_rejection_reason"] = "hard_constraint_no_match"
                else:
                    state.ambiguity_reason = "structured_no_match"

        state.query_product_ids = list(product_ids)
        debug_meta["catalog_query_product_ids"] = list(product_ids)
        if state.query_cache_key and product_ids:
            await self._component_cache.set_json(
                state.query_cache_key,
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
        state.result_count = len(product_ids)
        state.retrieval_source = retrieval_source
        state.retrieval_outcome = build_retrieval_outcome(
            retrieval_source=retrieval_source,
            product_ids=product_ids,
            ambiguity_reason=str(state.ambiguity_reason or ""),
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
        debug_meta["match_tier"] = state.retrieval_outcome.match_tier
        debug_meta["retrieval_outcome"] = state.retrieval_outcome.to_debug_dict()
        state.semantic_catalog_search_done = True


        return True, product_ids, query_embedding

