from __future__ import annotations

import time
from typing import Any, Dict, Sequence

from app.services.chat.components.pipeline_runtime.catalog_search import PipelineCatalogSearchMixin
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.pipeline_runtime.workflow_detail import PipelineWorkflowDetailMixin
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.presentation import product_presentation
from app.services.chat.text_normalization import normalize_user_text


class PipelineWorkflowCatalogMixin(PipelineCatalogSearchMixin, PipelineWorkflowDetailMixin):
    _ATTRIBUTE_LIST_LABELS = {
        "gauge": "gauge options",
        "material": "material options",
        "jewelry_type": "jewelry type options",
        "body_part": "body part options",
        "presentation_type": "presentation type options",
        "feature": "feature options",
        "color": "color options",
        "threading": "threading options",
        "theme": "theme options",
    }

    @staticmethod
    def _select_catalog_components(
            *,
            text: str,
            workflow: str,
            detail: Any,
            product_ids: Sequence[Any],
            ambiguity_reason: str,
        ) -> list[ComponentType]:
            text_norm = normalize_user_text(text)
            workflow_norm = normalize_user_text(workflow)
            if not text_norm:
                return [ComponentType.ERROR]
            if bool(ambiguity_reason):
                return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
            if workflow_norm == "knowledge":
                return [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            if workflow_norm == "catalog" and len(list(product_ids or [])) <= 0:
                return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
            components = [ComponentType.QUERY_SUMMARY]
            if bool(getattr(detail, "is_detail_request", False)):
                components.append(ComponentType.PRODUCT_DETAIL)
            else:
                components.append(ComponentType.PRODUCT_CARDS)
            return list(dict.fromkeys(components))

    @staticmethod
    def _attribute_list_scope_label(*, attribute_filters: Dict[str, str]) -> str:
        filters = dict(attribute_filters or {})
        material = str(filters.get("material") or "").strip()
        jewelry_type = str(filters.get("jewelry_type") or "").strip()
        if material and jewelry_type:
            return f"{material.lower()} {jewelry_type.lower()}"
        if material:
            return f"{material.lower()} jewelry"
        if jewelry_type:
            return jewelry_type.lower()
        return "matching products"

    @classmethod
    def _attribute_list_display_label(cls, target: str) -> str:
        target_norm = str(target or "").strip().lower()
        if not target_norm:
            return "available options"
        return cls._ATTRIBUTE_LIST_LABELS.get(target_norm, f"{target_norm.replace('_', ' ')} options")

    @staticmethod
    def _join_display_values(values: Sequence[str]) -> str:
        items = [str(item or "").strip() for item in list(values or []) if str(item or "").strip()]
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return ", ".join(items[:-1]) + f", and {items[-1]}"

    async def _handle_attribute_list_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            workflow: str,
            detail: Any,
            attribute_list_target: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> bool:
            del workflow, external_call_counts
            target = str(attribute_list_target or "").strip().lower()
            if not target:
                return False

            attribute_filters = dict(getattr(detail, "attribute_filters", {}) or {})
            target_values: list[str] = []
            load_started = time.perf_counter()
            try:
                target_values = await self._load_distinct_attribute_values(
                    target=target,
                    attribute_filters=attribute_filters,
                    limit=6,
                )
            except Exception as exc:
                debug_meta["attribute_list_error"] = str(exc)
                target_values = []
            finally:
                spans["db_product_lookup_ms"] += (time.perf_counter() - load_started) * 1000.0

            debug_meta["attribute_list_target"] = target
            debug_meta["attribute_list_query_text"] = str(text or "").strip()
            debug_meta["attribute_list_value_count"] = int(len(target_values))
            debug_meta["attribute_list_values"] = list(target_values)

            state.catalog.handled_attribute_list = True
            state.catalog.attribute_list_target = target

            if not target_values:
                state.decision.ambiguity_reason = "attribute_list_no_results"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.presentation.canonical_products = []
                state.catalog.product_ids = []
                state.retrieval.result_count = 0
                state.retrieval.source = ComponentSource.ERROR
                debug_meta["attribute_list_no_results"] = True
                return True

            scope_label = self._attribute_list_scope_label(attribute_filters=attribute_filters)
            list_label = self._attribute_list_display_label(target)
            count = len(target_values)
            values_text = self._join_display_values(target_values)
            if scope_label == "matching products":
                reply = f"I found {count} {list_label}: {values_text}."
            else:
                reply = f"I found {count} {list_label} for {scope_label}: {values_text}."

            state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            state.knowledge.answer = reply
            state.knowledge.sources = []
            state.presentation.canonical_products = []
            state.catalog.product_ids = []
            state.retrieval.result_count = count
            state.retrieval.source = ComponentSource.SQL
            debug_meta["attribute_list_reply_text"] = reply
            return True

    async def _resolve_products(
            self,
            *,
            product_ids: Sequence[Any],
            component_types: Sequence[ComponentType],
    ) -> tuple[list[Any], Dict[str, Any]]:
            try:
                return await self._field_resolver.resolve(
                    product_ids=product_ids,
                    component_types=list(component_types),
                    component_cache=self._component_cache,
                )
            except TypeError:
                try:
                    return await self._field_resolver.resolve(
                        product_ids=product_ids,
                        component_types=list(component_types),
                        redis_cache=self._component_cache,
                    )
                except TypeError:
                    return await self._field_resolver.resolve(
                        product_ids=product_ids,
                        component_types=list(component_types),
                    )

    async def _resolve_products_with_metrics(
            self,
            *,
            product_ids: Sequence[Any],
            component_types: Sequence[ComponentType],
            spans: Dict[str, float],
            debug_meta: Dict[str, Any],
        ) -> tuple[list[Any], Dict[str, Any]]:
            resolver_started = time.perf_counter()
            products, resolver_meta = await self._resolve_products(
                product_ids=product_ids,
                component_types=component_types,
            )
            spans["db_product_lookup_ms"] += (time.perf_counter() - resolver_started) * 1000.0
            debug_meta.update(resolver_meta)
            return products, resolver_meta

    @staticmethod
    def _build_catalog_pagination_context(
            *,
            display_limit: int,
            pagination_offset: int,
            pagination_limit: int,
            pagination_query_cache_key: str,
        ) -> tuple[int, int, str]:
            page_size = max(1, int(pagination_limit or display_limit or product_presentation.PRODUCT_DISPLAY_LIMIT))
            page_offset = max(0, int(pagination_offset or 0)) + page_size
            cache_key = str(pagination_query_cache_key or "").strip()
            return page_size, page_offset, cache_key

    async def _load_catalog_pagination_ids(
            self,
            *,
            cache_key: str,
            fallback_product_ids: Sequence[str],
            debug_meta: Dict[str, Any],
        ) -> tuple[list[str], str, int]:
            cached_ids_payload = await self._component_cache.get_json(cache_key) if cache_key else None
            full_product_ids = list(cached_ids_payload.get("product_ids") or []) if isinstance(cached_ids_payload, dict) else []
            cached_source = str(cached_ids_payload.get("source") or "vector") if isinstance(cached_ids_payload, dict) else "vector"
            total_count = max(
                int(cached_ids_payload.get("result_count") or 0) if isinstance(cached_ids_payload, dict) else 0,
                len(full_product_ids),
            )
            if not full_product_ids:
                full_product_ids = [str(item).strip() for item in list(fallback_product_ids or []) if str(item).strip()]
                total_count = max(total_count, len(full_product_ids))
                cached_source = "vector"
                debug_meta["catalog_pagination_state_fallback_used"] = bool(full_product_ids)
            debug_meta["catalog_pagination_cache_hit"] = bool(full_product_ids)
            debug_meta["catalog_pagination_total_count"] = int(total_count)
            debug_meta["catalog_query_cache_key"] = cache_key
            debug_meta["catalog_query_product_ids"] = list(full_product_ids)
            return full_product_ids, cached_source, total_count

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
            display_limit: int,
            pagination_query_cache_key: str,
            pagination_query_product_ids: Sequence[str],
            pagination_offset: int,
            pagination_limit: int,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> None:
            del locale, workflow, detail, store_overview_request, unique_sku_tokens, external_call_counts
            page_size, page_offset, cache_key = self._build_catalog_pagination_context(
                display_limit=display_limit,
                pagination_offset=pagination_offset,
                pagination_limit=pagination_limit,
                pagination_query_cache_key=pagination_query_cache_key,
            )
            debug_meta["catalog_pagination_requested"] = True
            debug_meta["catalog_pagination_offset"] = page_offset
            debug_meta["catalog_pagination_limit"] = page_size
            state.catalog.pagination_requested = True
            state.catalog.pagination_offset = page_offset
            state.catalog.pagination_limit = page_size
            state.catalog.pagination_has_more = False
            state.catalog.query_cache_key = cache_key
            full_product_ids, cached_source, total_count = await self._load_catalog_pagination_ids(
                cache_key=cache_key,
                fallback_product_ids=pagination_query_product_ids,
                debug_meta=debug_meta,
            )
            if not full_product_ids:
                state.decision.ambiguity_reason = "pagination_unavailable"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.retrieval.source = ComponentSource.ERROR
                state.retrieval.result_count = 0
                debug_meta["catalog_pagination_error"] = "missing_pagination_state"
                return

            full_products, _resolver_meta = await self._resolve_products_with_metrics(
                product_ids=full_product_ids,
                component_types=[ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS],
                spans=spans,
                debug_meta=debug_meta,
            )
            unique_products, total_unique_products = product_presentation.dedupe_products_by_master_code(
                full_products,
                limit=max(len(full_products), 1),
            )
            total_count = max(total_count, int(total_unique_products))
            page_products = list(unique_products[page_offset: page_offset + page_size])
            state.retrieval.result_count = total_count
            state.presentation.canonical_products = list(page_products)
            state.catalog.product_ids = [self._card_identifier(card) for card in page_products]
            state.catalog.query_product_ids = list(full_product_ids)
            state.retrieval.source = (
                ComponentSource(cached_source)
                if cached_source in {item.value for item in ComponentSource}
                else ComponentSource.VECTOR
            )
            state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]

            if not page_products:
                state.decision.ambiguity_reason = "pagination_exhausted"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.presentation.canonical_products = []
                state.retrieval.source = ComponentSource.SQL
                debug_meta["catalog_pagination_exhausted"] = True
                debug_meta["catalog_pagination_has_more"] = False
                return

            state.catalog.pagination_has_more = (page_offset + len(page_products)) < total_count
            debug_meta["catalog_pagination_has_more"] = state.catalog.pagination_has_more
            debug_meta["catalog_pagination_page_count"] = len(page_products)
            debug_meta["catalog_pagination_source"] = state.retrieval.source.value
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
            display_limit: int,
            result_fetch_limit: int,
            normalized_text: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> None:
            if state.decision.ambiguity_reason or state.catalog.handled_attribute_list:
                return

            if store_overview_request:
                product_ids = list(state.catalog.product_ids or [])
                if not product_ids:
                    state.decision.ambiguity_reason = "store_overview_no_results"
                    state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    state.retrieval.result_count = 0
                    state.retrieval.source = ComponentSource.ERROR
                    return

                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                state.presentation.canonical_products, _resolver_meta = await self._resolve_products_with_metrics(
                    product_ids=product_ids,
                    component_types=state.presentation.selected_components,
                    spans=spans,
                    debug_meta=debug_meta,
                )
                state.retrieval.result_count = max(state.retrieval.result_count, len(state.presentation.canonical_products))
                state.retrieval.source = ComponentSource.SQL
                debug_meta["store_overview_reply"] = self._build_store_overview_reply(products=state.presentation.canonical_products)
                debug_meta["store_overview_follow_ups"] = self._build_store_overview_follow_ups(
                    products=state.presentation.canonical_products,
                    limit=4,
                )
                return

            handled, product_ids, _query_embedding = await self._run_catalog_retrieval_workflow(
                state=state,
                text=text,
                locale=locale,
                workflow=workflow,
                detail=detail,
                unique_sku_tokens=unique_sku_tokens,
                result_fetch_limit=result_fetch_limit,
                normalized_text=normalized_text,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            if not handled:
                return


            if state.catalog.semantic_search_done:
                debug_meta["semantic_first_used"] = True

            state.presentation.selected_components = self._select_catalog_components(
                text=text,
                workflow=workflow,
                detail=detail,
                product_ids=product_ids,
                ambiguity_reason=str(state.decision.ambiguity_reason or ""),
            )
            state.presentation.canonical_products, _resolver_meta = await self._resolve_products_with_metrics(
                product_ids=product_ids,
                component_types=state.presentation.selected_components,
                spans=spans,
                debug_meta=debug_meta,
            )
            state.retrieval.result_count = max(state.retrieval.result_count, len(state.presentation.canonical_products))

            if store_overview_request and state.presentation.canonical_products:
                debug_meta["store_overview_reply"] = self._build_store_overview_reply(products=state.presentation.canonical_products)
                debug_meta["store_overview_follow_ups"] = self._build_store_overview_follow_ups(
                    products=state.presentation.canonical_products,
                    limit=4,
                )

            self._handle_detail_workflow(
                state=state,
                detail=detail,
                unique_sku_tokens=unique_sku_tokens,
                debug_meta=debug_meta,
            )

            self._finalize_catalog_products(
                state=state,
                detail=detail,
                display_limit=display_limit,
                debug_meta=debug_meta,
            )
