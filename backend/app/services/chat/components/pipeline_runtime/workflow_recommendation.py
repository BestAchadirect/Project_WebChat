from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from app.services.ai.llm_service import llm_service
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState


class PipelineWorkflowRecommendationMixin:
    async def _handle_recommendation_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            detail: Any,
            recommendation_requested: bool,
            recommendation_mode_requested: str,
            result_fetch_limit: int,
            query_embedding: Optional[List[float]],
            product_ids: List[Any],
            unique_sku_tokens: Sequence[str],
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> List[Any]:
            if not recommendation_requested or not state.canonical_products:
                return product_ids

            anchor_products = list(state.canonical_products[:3])
            anchor_ids = [item.product_id for item in anchor_products]
            recommendation_mode = self._recommendation_service.resolve_mode(
                requested_mode=recommendation_mode_requested,
                user_text=text,
                anchor_products=anchor_products,
                attribute_filters=detail.attribute_filters,
            )
            debug_meta["recommendation_mode_requested"] = recommendation_mode
            expansion_product_ids: List[Any] = []
            recommendation_distance_by_id: Dict[str, float] = {}

            if recommendation_mode == "complementary_items":
                complementary_profile = self._recommendation_service.build_complementary_profile(
                    anchor_products=anchor_products,
                    attribute_filters=detail.attribute_filters,
                )
                if complementary_profile is not None:
                    debug_meta["recommendation_complementary_label"] = complementary_profile.label
                    debug_meta["recommendation_complementary_query"] = complementary_profile.search_query
                    try:
                        embed_started = time.perf_counter()
                        complementary_embedding = await llm_service.generate_embedding(
                            complementary_profile.search_query
                        )
                        spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                        external_call_counts["embedding_recommendation_complementary"] = (
                            int(external_call_counts.get("embedding_recommendation_complementary", 0)) + 1
                        )
                        vector_started = time.perf_counter()
                        complementary_result = await self._catalog_search.vector_search(
                            query_embedding=list(complementary_embedding or []),
                            limit=result_fetch_limit,
                            candidate_limit=max(result_fetch_limit * 4, 36),
                        )
                        spans["vector_search_ms"] += (time.perf_counter() - vector_started) * 1000.0
                        expansion_product_ids = [
                            self._card_identifier(card) for card in list(complementary_result.cards or [])
                        ]
                        recommendation_distance_by_id.update(
                            {
                                str(key): float(value)
                                for key, value in dict(complementary_result.distance_by_id or {}).items()
                            }
                        )
                        debug_meta["recommendation_expand_source"] = "complementary_mapping"
                        debug_meta["recommendation_used_anchor_embedding"] = False
                        debug_meta["recommendation_used_query_embedding"] = True
                        debug_meta["recommendation_expand_count"] = int(len(expansion_product_ids))
                    except Exception as exc:
                        debug_meta["recommendation_complementary_expand_error"] = str(exc)
                else:
                    debug_meta["recommendation_complementary_profile_missing"] = True

            if not expansion_product_ids:
                reco_started = time.perf_counter()
                expansion = await self._recommendation_service.expand_card_candidates(
                    anchor_product_ids=anchor_ids,
                    query_embedding=query_embedding,
                    limit=result_fetch_limit,
                )
                spans["vector_search_ms"] += (time.perf_counter() - reco_started) * 1000.0
                debug_meta["recommendation_expand_source"] = expansion.source
                debug_meta["recommendation_used_anchor_embedding"] = expansion.used_anchor_embedding
                debug_meta["recommendation_used_query_embedding"] = expansion.used_query_embedding
                debug_meta["recommendation_expand_count"] = int(len(expansion.product_ids))
                expansion_product_ids = list(expansion.product_ids or [])
                recommendation_distance_by_id.update(
                    {str(key): float(value) for key, value in dict(expansion.distance_by_id or {}).items()}
                )

            if expansion_product_ids:
                existing_ids = {str(item) for item in list(product_ids or [])}
                extra_ids = [item for item in expansion_product_ids if str(item) not in existing_ids]
                if extra_ids:
                    merged_ids = list(product_ids) + extra_ids
                    resolver_started = time.perf_counter()
                    state.canonical_products, resolver_meta = await self._field_resolver.resolve(
                        product_ids=merged_ids,
                        component_types=state.selected_components,
                        component_cache=self._component_cache,
                    )
                    spans["db_product_lookup_ms"] += (time.perf_counter() - resolver_started) * 1000.0
                    debug_meta.update(resolver_meta)
                    product_ids = merged_ids
                    state.product_ids = list(product_ids)
                    debug_meta["recommendation_expand_added_ids"] = int(len(extra_ids))

            try:
                ranked = self._recommendation_service.rank_canonical_products(
                    candidates=state.canonical_products,
                    attribute_filters=detail.attribute_filters,
                    user_text=text,
                    distance_by_id=recommendation_distance_by_id,
                    anchor_products=anchor_products,
                    limit=None,
                    recommendation_mode=recommendation_mode,
                    exclude_product_ids=anchor_ids
                    if (unique_sku_tokens or recommendation_mode == "complementary_items")
                    else None,
                )
            except TypeError:
                ranked = self._recommendation_service.rank_canonical_products(
                    candidates=state.canonical_products,
                    attribute_filters=detail.attribute_filters,
                    user_text=text,
                    distance_by_id=recommendation_distance_by_id,
                    anchor_products=anchor_products,
                    limit=None,
                    exclude_product_ids=anchor_ids
                    if (unique_sku_tokens or recommendation_mode == "complementary_items")
                    else None,
                )
            debug_meta.update(ranked.meta)
            if ranked.items:
                state.canonical_products = list(ranked.items)
                ranked_ids = [self._card_identifier(card) for card in list(ranked.items)]
                state.product_ids = list(ranked_ids)
                state.query_product_ids = list(ranked_ids)
                debug_meta["catalog_query_product_ids"] = list(ranked_ids)
            state.recommendations = list(state.canonical_products[:5])
            return product_ids
