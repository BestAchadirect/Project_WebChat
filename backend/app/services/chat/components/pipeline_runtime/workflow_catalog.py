from __future__ import annotations

import time
from typing import Any, Dict, Sequence

from app.services.chat.components.pipeline_runtime.catalog_search import PipelineCatalogSearchMixin
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.pipeline_runtime.workflow_detail import PipelineWorkflowDetailMixin
from app.services.chat.components.pipeline_runtime.workflow_recommendation import PipelineWorkflowRecommendationMixin
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.presentation import product_presentation


class PipelineWorkflowCatalogMixin(PipelineCatalogSearchMixin, PipelineWorkflowRecommendationMixin, PipelineWorkflowDetailMixin):
    async def _handle_catalog_pagination_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            workflow: str,
            detail: Any,
            store_overview_request: bool,
            unique_sku_tokens: Sequence[str],
            recommendation_requested: bool,
            display_limit: int,
            pagination_query_cache_key: str,
            pagination_offset: int,
            pagination_limit: int,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> None:
            del locale, workflow, detail, store_overview_request, unique_sku_tokens, recommendation_requested, external_call_counts
            page_size = max(1, int(pagination_limit or display_limit or product_presentation.PRODUCT_DISPLAY_LIMIT))
            page_offset = max(0, int(pagination_offset or 0)) + page_size
            debug_meta["catalog_pagination_requested"] = True
            debug_meta["catalog_pagination_offset"] = page_offset
            debug_meta["catalog_pagination_limit"] = page_size
            cache_key = str(pagination_query_cache_key or "").strip()
            debug_meta["catalog_pagination_query_cache_key"] = cache_key
            state.pagination_requested = True
            state.pagination_offset = page_offset
            state.pagination_limit = page_size
            state.pagination_has_more = False
            state.query_cache_key = cache_key
            if not cache_key:
                state.ambiguity_reason = "pagination_unavailable"
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.retrieval_source = ComponentSource.ERROR
                state.result_count = 0
                debug_meta["catalog_pagination_error"] = "missing_query_cache_key"
                return

            cached_ids_payload = await self._redis_cache.get_json(cache_key)
            full_product_ids = list(cached_ids_payload.get("product_ids") or []) if isinstance(cached_ids_payload, dict) else []
            cached_source = str(cached_ids_payload.get("source") or "vector") if isinstance(cached_ids_payload, dict) else "vector"
            total_count = max(
                int(cached_ids_payload.get("result_count") or 0) if isinstance(cached_ids_payload, dict) else 0,
                len(full_product_ids),
            )
            debug_meta["catalog_pagination_cache_hit"] = bool(full_product_ids)
            debug_meta["catalog_pagination_total_count"] = int(total_count)
            if not full_product_ids:
                state.ambiguity_reason = "pagination_unavailable"
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.retrieval_source = ComponentSource.ERROR
                state.result_count = 0
                debug_meta["catalog_pagination_error"] = "empty_query_cache"
                return

            resolver_started = time.perf_counter()
            full_products, resolver_meta = await self._field_resolver.resolve(
                product_ids=full_product_ids,
                component_types=[ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS],
                redis_cache=self._redis_cache,
            )
            spans["db_product_lookup_ms"] += (time.perf_counter() - resolver_started) * 1000.0
            debug_meta.update(resolver_meta)
            unique_products, total_unique_products = product_presentation.dedupe_products_by_master_code(
                full_products,
                limit=max(len(full_products), 1),
            )
            total_count = max(total_count, int(total_unique_products))
            page_products = list(unique_products[page_offset: page_offset + page_size])
            state.result_count = total_count
            state.canonical_products = list(page_products)
            state.product_ids = [self._card_identifier(card) for card in page_products]
            state.retrieval_source = (
                ComponentSource(cached_source)
                if cached_source in {item.value for item in ComponentSource}
                else ComponentSource.VECTOR
            )
            state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]

            if not page_products:
                state.ambiguity_reason = "pagination_exhausted"
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.canonical_products = []
                state.recommendations = []
                state.retrieval_source = ComponentSource.SQL
                debug_meta["catalog_pagination_exhausted"] = True
                debug_meta["catalog_pagination_has_more"] = False
                return

            state.pagination_has_more = (page_offset + len(page_products)) < total_count
            debug_meta["catalog_pagination_has_more"] = state.pagination_has_more
            debug_meta["catalog_pagination_page_count"] = len(page_products)
            debug_meta["catalog_pagination_source"] = state.retrieval_source.value
            debug_meta["catalog_pagination_query_text"] = str(text or "").strip()

    async def _handle_catalog_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            workflow: str,
            detail: Any,
            store_overview_request: bool,
            unique_sku_tokens: Sequence[str],
            recommendation_requested: bool,
            display_limit: int,
            result_fetch_limit: int,
            normalized_text: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> None:
            if state.ambiguity_reason or state.handled_attribute_list:
                return

            if store_overview_request:
                product_ids = list(state.product_ids or [])
                if not product_ids:
                    state.ambiguity_reason = "store_overview_no_results"
                    state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    state.result_count = 0
                    state.retrieval_source = ComponentSource.ERROR
                    return

                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                resolver_started = time.perf_counter()
                state.canonical_products, resolver_meta = await self._field_resolver.resolve(
                    product_ids=product_ids,
                    component_types=state.selected_components,
                    redis_cache=self._redis_cache,
                )
                spans["db_product_lookup_ms"] += (time.perf_counter() - resolver_started) * 1000.0
                debug_meta.update(resolver_meta)
                state.result_count = max(state.result_count, len(state.canonical_products))
                state.retrieval_source = ComponentSource.SQL
                debug_meta["store_overview_reply"] = self._build_store_overview_reply(products=state.canonical_products)
                debug_meta["store_overview_follow_ups"] = self._build_store_overview_follow_ups(
                    products=state.canonical_products,
                    limit=4,
                )
                return

            handled, product_ids, query_embedding = await self._run_catalog_retrieval_workflow(
                state=state,
                text=text,
                locale=locale,
                workflow=workflow,
                detail=detail,
                unique_sku_tokens=unique_sku_tokens,
                recommendation_requested=recommendation_requested,
                result_fetch_limit=result_fetch_limit,
                normalized_text=normalized_text,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            if not handled:
                return


            if state.semantic_catalog_search_done:
                debug_meta["semantic_first_used"] = True

            state.selected_components = self._plan_components(
                user_text=text,
                workflow=workflow,
                product_count=len(product_ids),
                is_detail_mode=bool(detail.is_detail_request),
                is_ambiguous=bool(state.ambiguity_reason),
            )
            if (
                recommendation_requested
                and product_ids
                and ComponentType.RECOMMENDATIONS not in state.selected_components
            ):
                state.selected_components.append(ComponentType.RECOMMENDATIONS)

            resolver_started = time.perf_counter()
            state.canonical_products, resolver_meta = await self._field_resolver.resolve(
                product_ids=product_ids,
                component_types=state.selected_components,
                redis_cache=self._redis_cache,
            )
            spans["db_product_lookup_ms"] += (time.perf_counter() - resolver_started) * 1000.0
            debug_meta.update(resolver_meta)
            state.result_count = max(state.result_count, len(state.canonical_products))

            if store_overview_request and state.canonical_products:
                debug_meta["store_overview_reply"] = self._build_store_overview_reply(products=state.canonical_products)
                debug_meta["store_overview_follow_ups"] = self._build_store_overview_follow_ups(
                    products=state.canonical_products,
                    limit=4,
                )

            self._handle_detail_workflow(
                state=state,
                detail=detail,
                unique_sku_tokens=unique_sku_tokens,
                recommendation_requested=recommendation_requested,
                debug_meta=debug_meta,
            )

            product_ids = await self._handle_recommendation_workflow(
                state=state,
                text=text,
                detail=detail,
                recommendation_requested=recommendation_requested,
                result_fetch_limit=result_fetch_limit,
                query_embedding=query_embedding,
                product_ids=product_ids,
                unique_sku_tokens=unique_sku_tokens,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )

            self._finalize_catalog_products(
                state=state,
                detail=detail,
                display_limit=display_limit,
                recommendation_requested=recommendation_requested,
                debug_meta=debug_meta,
            )
