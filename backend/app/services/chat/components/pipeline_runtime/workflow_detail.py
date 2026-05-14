from __future__ import annotations

from typing import Any, Dict, Sequence

from app.core.config import settings
from app.services.chat.components.types import ComponentType
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.presentation.detail_response_builder import DetailResponseBuilder
from app.services.chat.retrieval.product_detail_resolver import ProductDetailResolver
from app.services.chat.presentation import product_presentation
from app.services.chat.text_normalization import normalize_user_text


class PipelineWorkflowDetailMixin:
    @staticmethod
    def _requested_field_set(requested_fields: Sequence[str]) -> set[str]:
        return {
            str(item or "").strip().lower()
            for item in list(requested_fields or [])
            if str(item or "").strip()
        }

    @classmethod
    def _detail_request_should_browse(
            cls,
            *,
            requested_fields: Sequence[str],
            attribute_filters: Dict[str, str],
            wants_image: bool,
            match_count: int,
            has_exact_match: bool,
            unique_sku_tokens: Sequence[str],
        ) -> bool:
            if has_exact_match or list(unique_sku_tokens or []) or int(match_count) <= 1:
                return False
            if not dict(attribute_filters or {}):
                return False

            fields = cls._requested_field_set(requested_fields)
            if bool(wants_image):
                fields.add("image")
            return bool(fields) and fields.issubset({"price", "stock", "image"})

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

    @staticmethod
    def _card_master_code(card: Any) -> str:
        attrs = dict(getattr(card, "attributes", {}) or {})
        for raw_key, raw_value in attrs.items():
            if str(raw_key or "").strip().lower() != "master_code":
                continue
            value = str(raw_value or "").strip()
            if value:
                return value
        return ""

    @classmethod
    def _build_related_product_query(
            cls,
            *,
            seed_cards: Sequence[Any],
            semantic_hints: Sequence[str],
        ) -> str:
        representative = list(seed_cards or [None])[0]
        parts: list[str] = []
        if representative is not None:
            for raw_value in (
                getattr(representative, "name", ""),
                getattr(representative, "title", ""),
                getattr(representative, "description", ""),
                getattr(representative, "material", ""),
            ):
                text = str(raw_value or "").strip()
                if text:
                    parts.append(text)

            attrs = dict(getattr(representative, "attributes", {}) or {})
            for key in (
                "jewelry_type",
                "feature",
                "design",
                "color",
                "gauge",
                "length",
                "size",
                "outer_diameter",
                "ring_size",
                "threading",
                "category",
            ):
                text = str(attrs.get(key) or "").strip()
                if text:
                    parts.append(text)

        for raw_hint in list(semantic_hints or []):
            hint = normalize_user_text(raw_hint)
            if hint:
                parts.append(hint)

        return normalize_user_text(" ".join(parts))

    async def _load_related_product_cards(
            self,
            *,
            seed_cards: Sequence[Any],
            semantic_hints: Sequence[str],
            limit: int,
        ) -> tuple[str, list[Any]]:
        master_codes = {
            self._card_master_code(card).lower().strip()
            for card in list(seed_cards or [])
            if self._card_master_code(card).strip()
        }
        clean_hints = [
            normalize_user_text(hint)
            for hint in list(semantic_hints or [])
            if normalize_user_text(hint)
        ]
        if not master_codes or not clean_hints:
            return "", []

        query_text = self._build_related_product_query(seed_cards=seed_cards, semantic_hints=clean_hints)
        if not query_text:
            return "", []

        candidate_limit = max(int(limit) * 4, int(limit) + 6, 12)
        try:
            search_result = await self._catalog_search.lexical_search(
                query_text=query_text,
                limit=candidate_limit,
                candidate_limit=candidate_limit,
            )
        except Exception:
            return query_text, []

        related_cards: list[Any] = []
        seen_ids: set[str] = set()
        for card in list(getattr(search_result, "cards", []) or []):
            card_id = self._card_identifier(card)
            if not card_id or card_id in seen_ids:
                continue
            master_code = self._card_master_code(card).lower().strip()
            if master_code and master_code in master_codes:
                continue
            seen_ids.add(card_id)
            related_cards.append(card)
            if len(related_cards) >= max(1, int(limit)):
                break

        return query_text, related_cards

    async def _handle_detail_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            detail: Any,
            unique_sku_tokens: Sequence[str],
            text: str,
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
            if self._detail_request_should_browse(
                requested_fields=resolution.requested_fields,
                attribute_filters=resolution.attribute_filters,
                wants_image=bool(getattr(detail, "wants_image", False)),
                match_count=len(resolution.matches),
                has_exact_match=resolution.has_exact_match,
                unique_sku_tokens=unique_sku_tokens,
            ):
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                state.retrieval.result_count = max(
                    int(state.retrieval.result_count or 0),
                    int(len(state.presentation.canonical_products or [])),
                )
                debug_meta["detail_broad_request_as_catalog"] = True
                debug_meta["detail_broad_request_fields"] = list(resolution.requested_fields or [])
                return
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
                detail_products = [
                    detail_by_id[self._card_identifier(card)]
                    for card in list(detail_payload.product_carousel or [])
                    if self._card_identifier(card) in detail_by_id
                ]
                state.presentation.canonical_products = list(detail_products)

                related_cards: list[Any] = []
                related_query = ""
                if (
                    not bool(getattr(detail, "wants_image", False))
                    and bool(list(getattr(detail, "semantic_hints", []) or []))
                    and len({
                        self._card_master_code(card).lower().strip()
                        for card in list(state.presentation.canonical_products or [])
                        if self._card_master_code(card).strip()
                    }) == 1
                ):
                    related_limit = max(
                        1,
                        min(
                            3,
                            int(getattr(settings, "CHAT_DETAIL_RELATED_MATCHES", 3)),
                        ),
                    )
                    related_query, related_cards = await self._load_related_product_cards(
                        seed_cards=state.presentation.canonical_products,
                        semantic_hints=list(getattr(detail, "semantic_hints", []) or []),
                        limit=related_limit,
                    )
                if related_cards:
                    state.presentation.canonical_products.extend(related_cards)
                    detail_text = str(detail_payload.reply_text or "").strip()
                    if detail_text:
                        if detail_text[-1:] not in {".", "!", "?"}:
                            detail_text = f"{detail_text}."
                        detail_text = f"{detail_text} I also found a few related options you might like."
                    else:
                        detail_text = "I also found a few related options you might like."
                    carousel_msg = str(detail_payload.carousel_msg or "").strip()
                    if carousel_msg:
                        carousel_msg = f"{carousel_msg} Related options are included below."
                    else:
                        carousel_msg = "Related options are shown below."
                    debug_meta["detail_reply_text"] = detail_text
                    debug_meta["detail_carousel_msg"] = carousel_msg
                    debug_meta["detail_related_products_used"] = True
                    debug_meta["detail_related_product_count"] = len(related_cards)
                    debug_meta["detail_related_search_query"] = related_query
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
        if bool(detail.is_detail_request) and not bool(debug_meta.get("detail_broad_request_as_catalog")):
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
        debug_meta["final_product_count"] = int(len(display_products))
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
