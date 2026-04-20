from __future__ import annotations

from typing import Any, Dict, Sequence

from app.core.config import settings
from app.services.chat.components.types import ComponentType
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.presentation.detail_response_builder import DetailResponseBuilder
from app.services.chat.retrieval.product_detail_resolver import ProductDetailResolver
from app.services.chat.presentation import product_presentation


class PipelineWorkflowDetailMixin:
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

    def _handle_detail_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            detail: Any,
            unique_sku_tokens: Sequence[str],
            debug_meta: Dict[str, Any],
        ) -> None:
        if detail.is_detail_request and state.presentation.canonical_products:
            candidate_cards = [self._to_product_card(item) for item in state.presentation.canonical_products]
            resolution = ProductDetailResolver().resolve_detail_request(
                candidate_cards=candidate_cards,
                distance_by_id={self._card_identifier(card): 0.0 for card in candidate_cards},
                requested_fields=detail.requested_fields,
                attribute_filters=detail.attribute_filters,
                sku_token=unique_sku_tokens[0] if unique_sku_tokens else None,
                nlu_product_code=unique_sku_tokens[0] if unique_sku_tokens else None,
                max_matches=int(getattr(settings, "CHAT_DETAIL_MAX_MATCHES", 3)),
                min_confidence=float(getattr(settings, "CHAT_DETAIL_MIN_CONFIDENCE", 0.55)),
            )
            debug_meta["detail_match_count"] = len(resolution.matches)
            debug_meta["detail_has_exact_match"] = resolution.has_exact_match
            if self._detail_request_needs_specific_product(
                requested_fields=resolution.requested_fields,
                attribute_filters=resolution.attribute_filters,
                match_count=len(resolution.matches),
                has_exact_match=resolution.has_exact_match,
            ):
                state.decision.ambiguity_reason = "detail_request_needs_specific_product"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.presentation.canonical_products = []
            else:
                detail_payload = DetailResponseBuilder().build_detail_reply(
                    matches=resolution.matches,
                    requested_fields=resolution.requested_fields,
                    attribute_filters=resolution.attribute_filters,
                    missing_fields_by_product=resolution.missing_fields_by_product,
                    wants_image=detail.wants_image,
                    max_matches=int(getattr(settings, "CHAT_DETAIL_MAX_MATCHES", 3)),
                )
                debug_meta["detail_card_policy_reason"] = detail_payload.card_policy_reason
                debug_meta["detail_reply_text"] = detail_payload.reply_text
                debug_meta["detail_carousel_msg"] = detail_payload.carousel_msg
                debug_meta["detail_follow_ups"] = list(detail_payload.follow_up_questions or [])
                detail_by_id = {str(item.product_id): item for item in state.presentation.canonical_products}
                state.presentation.canonical_products = [
                    detail_by_id[self._card_identifier(card)]
                    for card in list(detail_payload.product_carousel or [])
                    if self._card_identifier(card) in detail_by_id
                ]
                state.retrieval.result_count = len(state.presentation.canonical_products)
                if state.presentation.canonical_products:
                    if (
                        str(detail_payload.card_policy_reason or "") == "image_master_grouped"
                        and len(state.presentation.canonical_products) > 1
                    ):
                        state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                    else:
                        state.presentation.selected_components = (
                            [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_DETAIL]
                            if len(state.presentation.canonical_products) == 1
                            else [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                        )
                else:
                    state.decision.ambiguity_reason = "detail_no_match"
                    state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
            if state.decision.ambiguity_reason == "detail_request_needs_specific_product":
                state.retrieval.result_count = 0
            elif not state.presentation.canonical_products and state.decision.ambiguity_reason != "detail_no_match":
                state.decision.ambiguity_reason = "detail_no_match"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]

    def _finalize_catalog_products(
            self,
            *,
            state: PipelineWorkflowState,
            detail: Any,
            display_limit: int,
            debug_meta: Dict[str, Any],
        ) -> None:
        if bool(detail.is_detail_request):
            display_products = list(state.presentation.canonical_products)
            total_unique_products = len(display_products)
        else:
            display_products, total_unique_products = product_presentation.dedupe_products_by_master_code(
                state.presentation.canonical_products,
                limit=display_limit,
            )
        debug_meta["raw_product_row_count"] = int(len(state.presentation.canonical_products))
        debug_meta["product_unique_master_count"] = int(total_unique_products)
        debug_meta["product_display_count"] = int(len(display_products))
        if not bool(state.catalog.pagination_requested):
            state.catalog.pagination_offset = 0
            state.catalog.pagination_limit = int(display_limit)
            state.catalog.pagination_has_more = bool(total_unique_products > len(display_products))
        debug_meta["product_overflow_available"] = bool(state.catalog.pagination_has_more)
        debug_meta["catalog_pagination_offset"] = int(state.catalog.pagination_offset or 0)
        debug_meta["catalog_pagination_limit"] = int(state.catalog.pagination_limit or display_limit)
        debug_meta["catalog_pagination_has_more"] = bool(state.catalog.pagination_has_more)
        state.presentation.canonical_products = list(display_products)
        state.retrieval.result_count = max(int(state.retrieval.result_count or 0), int(total_unique_products))
