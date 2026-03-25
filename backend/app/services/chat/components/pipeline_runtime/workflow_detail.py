from __future__ import annotations

from typing import Any, Dict, Sequence

from app.core.config import settings
from app.services.chat.components.types import ComponentType
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.presentation.detail_response_builder import DetailResponseBuilder
from app.services.chat.retrieval.product_detail_resolver import ProductDetailResolver
from app.services.chat.presentation import product_presentation


class PipelineWorkflowDetailMixin:
    def _handle_detail_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            detail: Any,
            unique_sku_tokens: Sequence[str],
            recommendation_requested: bool,
            debug_meta: Dict[str, Any],
        ) -> None:
        if detail.is_detail_request and state.canonical_products and not recommendation_requested:
            candidate_cards = [self._to_product_card(item) for item in state.canonical_products]
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
                state.ambiguity_reason = "detail_request_needs_specific_product"
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.canonical_products = []
                state.recommendations = []
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
                detail_by_id = {str(item.product_id): item for item in state.canonical_products}
                state.canonical_products = [
                    detail_by_id[self._card_identifier(card)]
                    for card in list(detail_payload.product_carousel or [])
                    if self._card_identifier(card) in detail_by_id
                ]
                state.result_count = len(state.canonical_products)
                if state.canonical_products:
                    if (
                        str(detail_payload.card_policy_reason or "") == "image_master_grouped"
                        and len(state.canonical_products) > 1
                    ):
                        state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                    else:
                        state.selected_components = (
                            [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_DETAIL]
                            if len(state.canonical_products) == 1
                            else [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                        )
                else:
                    state.ambiguity_reason = "detail_no_match"
                    state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    state.recommendations = []
            if state.ambiguity_reason == "detail_request_needs_specific_product":
                state.result_count = 0
            elif not state.canonical_products and state.ambiguity_reason != "detail_no_match":
                state.ambiguity_reason = "detail_no_match"
                state.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.recommendations = []

    def _finalize_catalog_products(
            self,
            *,
            state: PipelineWorkflowState,
            detail: Any,
            display_limit: int,
            recommendation_requested: bool,
            debug_meta: Dict[str, Any],
        ) -> None:
        if bool(detail.is_detail_request):
            display_products = list(state.canonical_products)
            total_unique_products = len(display_products)
        else:
            display_products, total_unique_products = product_presentation.dedupe_products_by_master_code(
                state.canonical_products,
                limit=display_limit,
            )
        debug_meta["raw_product_row_count"] = int(len(state.canonical_products))
        debug_meta["product_unique_master_count"] = int(total_unique_products)
        debug_meta["product_display_count"] = int(len(display_products))
        if not bool(getattr(state, "pagination_requested", False)):
            state.pagination_offset = 0
            state.pagination_limit = int(display_limit)
            state.pagination_has_more = bool(total_unique_products > len(display_products))
        debug_meta["product_overflow_available"] = bool(getattr(state, "pagination_has_more", False))
        debug_meta["catalog_pagination_offset"] = int(getattr(state, "pagination_offset", 0) or 0)
        debug_meta["catalog_pagination_limit"] = int(getattr(state, "pagination_limit", display_limit) or display_limit)
        debug_meta["catalog_pagination_has_more"] = bool(getattr(state, "pagination_has_more", False))
        state.canonical_products = list(display_products)
        state.result_count = max(int(state.result_count or 0), int(total_unique_products))
        if recommendation_requested and not state.recommendations:
            state.recommendations = list(state.canonical_products[:5])
