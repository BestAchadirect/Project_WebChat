from __future__ import annotations

import time
import re
from typing import Any, Dict, Sequence

from app.core.config import settings
from app.services.chat.components.pipeline_runtime.catalog_search import PipelineCatalogSearchMixin
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.pipeline_runtime.workflow_detail import PipelineWorkflowDetailMixin
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.presentation import product_presentation
from app.services.chat.routing import signals as routing_signals
from app.services.chat.runtime.grounding import GroundingDecision, evaluate_catalog_grounding
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
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
            if (
                str(ambiguity_reason or "").strip() == "structured_no_match"
                and dict(getattr(detail, "attribute_filters", {}) or {})
            ):
                if list(product_ids or []):
                    return [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                return [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
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

    @staticmethod
    def _display_filter_key(key: str) -> str:
        text = str(key or "").strip().replace("_", " ")
        if text.islower():
            return " ".join(part.capitalize() for part in text.split(" ") if part)
        return text

    @staticmethod
    def _display_filter_value(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.islower():
            return " ".join(part.capitalize() for part in text.split(" ") if part)
        return text

    @classmethod
    def _build_structured_no_match_reply(cls, *, attribute_filters: Dict[str, str]) -> str:
        del attribute_filters
        return (
            "I couldn't find an exact match for that request. "
            "I can show similar products or broaden the search if you'd like."
        )

    @staticmethod
    def _looks_like_related_product_followup(*, text: str) -> bool:
        text_norm = normalize_user_text(text)
        if not text_norm:
            return False
        return any(
            marker in text_norm
            for marker in (
                "similar product",
                "similar products",
                "similar option",
                "similar options",
                "related product",
                "related products",
                "related option",
                "related options",
                "another option",
                "other option",
                "another one",
                "same one",
                "same style",
                "like this",
                "like these",
            )
        )

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
    def _looks_like_context_price_followup(*, state: PipelineWorkflowState, detail: Any) -> bool:
            pending_task = str(getattr(state.decision, "pending_task_type", "") or "").strip().lower()
            missing_slot = str(getattr(state.decision, "missing_slot", "") or "").strip().lower()
            if pending_task in {"compare_price", "find_cheaper_products"} and missing_slot == "product_anchor":
                return True
            hints = {
                str(item or "").strip().lower()
                for item in list(getattr(detail, "semantic_hints", []) or [])
                if str(item or "").strip()
            }
            return bool(hints.intersection({"cheapest", "lower price", "cheaper", "lowest price", "budget"}))

    @staticmethod
    def _referenced_product_index(*, text: str) -> int | None:
            text_norm = normalize_user_text(text)
            if re.search(r"\b(first|1st)\s+(?:one|item|product)\b", text_norm):
                return 0
            if re.search(r"\b(second|2nd)\s+(?:one|item|product)\b", text_norm):
                return 1
            if re.search(r"\b(third|3rd)\s+(?:one|item|product)\b", text_norm):
                return 2
            return None

    @staticmethod
    def _requested_context_detail_fields(*, text: str, detail: Any) -> list[str]:
            fields = [
                str(item or "").strip().lower()
                for item in list(getattr(detail, "requested_fields", []) or [])
                if str(item or "").strip()
            ]
            text_norm = normalize_user_text(text)
            if any(term in text_norm for term in ("price", "cost", "how much")) and "price" not in fields:
                fields.append("price")
            if any(term in text_norm for term in ("stock", "available", "availability", "in stock")) and "stock" not in fields:
                fields.append("stock")
            return fields

    async def _handle_context_detail_reference_followup(
            self,
            *,
            state: PipelineWorkflowState,
            detail: Any,
            text: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
        ) -> bool:
            fields = self._requested_context_detail_fields(text=text, detail=detail)
            if not fields:
                return False
            product_ids = [
                str(item or "").strip()
                for item in list(debug_meta.get("conversation_last_product_ids") or [])
                if str(item or "").strip()
            ]
            if not product_ids:
                return False
            index = self._referenced_product_index(text=text)
            if index is None:
                if len(product_ids) != 1:
                    return False
                index = 0
            if index < 0 or index >= len(product_ids):
                return False

            selected_id = product_ids[index]
            component_types = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_DETAIL]
            products, _resolver_meta = await self._resolve_products_with_metrics(
                product_ids=[selected_id],
                component_types=component_types,
                spans=spans,
                debug_meta=debug_meta,
            )
            products = [product for product in list(products or []) if product is not None]
            if not products:
                return False
            product = products[0]
            title = str(getattr(product, "title", "") or getattr(product, "name", "") or getattr(product, "sku", "") or "that item").strip()
            reply_parts: list[str] = []
            if "price" in fields:
                try:
                    price = float(getattr(product, "price", 0.0) or 0.0)
                    currency = str(getattr(product, "currency", "") or "USD").strip() or "USD"
                    reply_parts.append(f"{title} is {price:.2f} {currency}.")
                except Exception:
                    reply_parts.append(f"I found {title}, but I couldn't confirm the price from the catalog data.")
            if "stock" in fields:
                stock = str(getattr(product, "stock_status", "") or "").strip()
                if stock:
                    reply_parts.append(f"Stock status: {stock}.")
            reply_text = " ".join(reply_parts).strip() or f"I found {title}."

            state.presentation.selected_components = component_types
            state.presentation.canonical_products = [product]
            state.catalog.product_ids = [selected_id]
            state.catalog.query_product_ids = [selected_id]
            state.retrieval.result_count = 1
            state.retrieval.source = ComponentSource.SQL
            state.catalog.pagination_has_more = False
            debug_meta["context_detail_followup_used"] = True
            debug_meta["context_detail_followup_index"] = int(index)
            debug_meta["detail_reply_text"] = reply_text
            debug_meta["detail_carousel_msg"] = "I included the referenced product below."
            return True

    @staticmethod
    def _looks_like_compare_request(*, text: str, unique_sku_tokens: Sequence[str]) -> bool:
            return routing_signals.looks_like_compare_request(text=text, sku_tokens=unique_sku_tokens)

    async def _handle_compare_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            unique_sku_tokens: Sequence[str],
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
        ) -> bool:
            compare_tokens = [
                str(token or "").strip()
                for token in list(dict.fromkeys([str(item).strip() for item in list(unique_sku_tokens or [])]))
                if str(token or "").strip()
            ]
            if len(compare_tokens) < 2:
                return False
            if not self._looks_like_compare_request(text=text, unique_sku_tokens=compare_tokens):
                return False

            capabilities = state.decision.runtime_capabilities or build_chat_runtime_capabilities()
            compare_cards: list[Any] = []
            compare_ids: list[str] = []
            missing_tokens: list[str] = []
            compare_started = time.perf_counter()
            for token in compare_tokens[:5]:
                try:
                    structured_result, _structured_meta = await self._catalog_search.structured_search(
                        sku_token=token,
                        attribute_filters={},
                        limit=1,
                        candidate_cap=int(capabilities.chat_structured_candidate_cap),
                        catalog_version=str(capabilities.chat_catalog_version),
                        return_ids_only=False,
                    )
                except Exception as exc:
                    debug_meta["compare_lookup_error"] = str(exc)
                    missing_tokens.append(token)
                    continue
                cards = list(structured_result.cards or [])
                if not cards:
                    missing_tokens.append(token)
                    continue
                representative = cards[0]
                card_id = self._card_identifier(representative)
                if card_id and card_id not in compare_ids:
                    compare_ids.append(card_id)
                    compare_cards.append(representative)
            spans["db_product_lookup_ms"] += (time.perf_counter() - compare_started) * 1000.0

            if len(compare_cards) < 2:
                if missing_tokens:
                    state.decision.ambiguity_reason = "compare_request_needs_specific_product"
                    state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    state.presentation.canonical_products = []
                    state.catalog.product_ids = []
                    state.catalog.query_product_ids = []
                    state.retrieval.result_count = 0
                    state.retrieval.source = ComponentSource.ERROR
                    debug_meta["compare_request_used"] = True
                    debug_meta["compare_request_missing_tokens"] = list(missing_tokens)
                    debug_meta["clarify_reason"] = state.decision.ambiguity_reason
                    debug_meta["detail_compare_requested"] = True
                    debug_meta["detail_compare_missing_tokens"] = list(missing_tokens)
                    return True
                return False

            compare_reply = product_presentation.build_compare_product_reply(
                products=compare_cards,
                user_text=text,
            )
            state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
            state.presentation.canonical_products = list(compare_cards)
            state.catalog.product_ids = list(compare_ids)
            state.catalog.query_product_ids = list(compare_ids)
            state.retrieval.result_count = len(compare_cards)
            state.retrieval.source = ComponentSource.SQL
            state.catalog.pagination_has_more = False
            debug_meta["compare_request_used"] = True
            debug_meta["compare_request_tokens"] = list(compare_tokens)
            debug_meta["compare_match_count"] = len(compare_cards)
            debug_meta["detail_reply_text"] = compare_reply
            debug_meta["detail_carousel_msg"] = "I compared the matching products below."
            debug_meta["detail_follow_ups"] = []
            debug_meta["detail_compare_requested"] = True
            return True

    async def _handle_context_product_followup(
            self,
            *,
            state: PipelineWorkflowState,
            detail: Any,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
        ) -> bool:
            if dict(getattr(detail, "attribute_filters", {}) or {}):
                return False
            if not self._looks_like_context_price_followup(state=state, detail=detail):
                return False
            product_ids = [
                str(item or "").strip()
                for item in list(debug_meta.get("conversation_last_product_ids") or [])
                if str(item or "").strip()
            ]
            if not product_ids:
                return False

            component_types = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
            products, _resolver_meta = await self._resolve_products_with_metrics(
                product_ids=product_ids,
                component_types=component_types,
                spans=spans,
                debug_meta=debug_meta,
            )
            products = [product for product in list(products or []) if product is not None]
            if not products:
                return False

            def _price(product: Any) -> float:
                try:
                    return float(getattr(product, "price", 0.0) or 0.0)
                except Exception:
                    return 0.0

            sorted_products = sorted(products, key=_price)
            cheapest = sorted_products[0]
            title = str(getattr(cheapest, "title", "") or getattr(cheapest, "sku", "") or "that option").strip()
            price = _price(cheapest)
            currency = str(getattr(cheapest, "currency", "") or "USD").strip() or "USD"
            state.presentation.selected_components = component_types
            state.presentation.canonical_products = [cheapest]
            state.catalog.product_ids = [self._card_identifier(cheapest)]
            state.catalog.query_product_ids = [self._card_identifier(product) for product in sorted_products if self._card_identifier(product)]
            state.retrieval.result_count = len(sorted_products)
            state.retrieval.source = ComponentSource.SQL
            debug_meta["context_product_followup_used"] = True
            debug_meta["context_product_followup_type"] = "price_compare"
            debug_meta["detail_reply_text"] = f"The cheapest option from the current results is {title} at {price:.2f} {currency}."
            debug_meta["detail_carousel_msg"] = "I included the cheapest matching product below."
            return True

    async def _handle_context_related_product_followup(
            self,
            *,
            state: PipelineWorkflowState,
            detail: Any,
            text: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
        ) -> bool:
            del detail
            if not self._looks_like_related_product_followup(text=text):
                return False
            product_ids = [
                str(item or "").strip()
                for item in list(debug_meta.get("conversation_last_product_ids") or [])
                if str(item or "").strip()
            ]
            if not product_ids:
                return False

            component_types = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
            products, _resolver_meta = await self._resolve_products_with_metrics(
                product_ids=product_ids,
                component_types=component_types,
                spans=spans,
                debug_meta=debug_meta,
            )
            products = [product for product in list(products or []) if product is not None]
            if not products:
                return False

            related_cards: list[Any] = []
            related_query = ""
            related_limit = max(1, min(3, int(getattr(settings, "CHAT_DETAIL_RELATED_MATCHES", 3))))
            related_query, related_cards = await self._load_related_product_cards(
                seed_cards=products,
                semantic_hints=["similar product"],
                limit=related_limit,
            )
            if related_cards:
                products = related_cards

            state.presentation.selected_components = component_types
            state.presentation.canonical_products = list(products)
            state.catalog.product_ids = [self._card_identifier(product) for product in products if self._card_identifier(product)]
            state.catalog.query_product_ids = list(state.catalog.product_ids)
            state.retrieval.result_count = len(products)
            state.retrieval.source = ComponentSource.SQL
            state.catalog.pagination_has_more = False

            debug_meta["context_related_product_followup_used"] = True
            debug_meta["context_related_product_followup_type"] = "similar_products"
            debug_meta["context_related_product_followup_count"] = len(products)
            debug_meta["context_related_product_followup_query"] = related_query
            debug_meta["detail_reply_text"] = "Here are some similar products you can browse."
            debug_meta["detail_carousel_msg"] = "Similar products are shown below."
            return True

    @classmethod
    def _apply_catalog_grounding(
            cls,
            *,
            state: PipelineWorkflowState,
            debug_meta: Dict[str, Any],
        ) -> None:
            plan = state.decision.search_plan
            if plan is None:
                return
            existing_ambiguity = str(state.decision.ambiguity_reason or "").strip()
            if bool(debug_meta.get("semantic_approximate_rescue_used")) and list(state.presentation.canonical_products or []):
                decision = GroundingDecision(
                    status="weak",
                    workflow=str(plan.workflow or "catalog"),
                    confidence=0.45,
                    reasons=["semantic_approximate_rescue"],
                    allowed_product_ids=[
                        cls._card_identifier(product)
                        for product in list(state.presentation.canonical_products or [])
                        if cls._card_identifier(product)
                    ],
                    safe_customer_action="show_close_matches",
                    debug={
                        "candidate_product_count": len(list(state.presentation.canonical_products or [])),
                        "grounded_product_count": len(list(state.presentation.canonical_products or [])),
                    },
                )
                state.decision.grounding_decision = decision
                debug_meta["grounding"] = decision.to_debug_dict()
                debug_meta["grounding_status"] = decision.status
                debug_meta["grounding_safe_action"] = decision.safe_customer_action
                debug_meta["grounding_reasons"] = list(decision.reasons)
                debug_meta.setdefault(
                    "detail_reply_text",
                    "I couldn't find an exact match, but here are the closest alternatives I found.",
                )
                debug_meta.setdefault("detail_carousel_msg", "Closest alternatives are shown below.")
                return
            decision = evaluate_catalog_grounding(
                plan=plan,
                products=list(state.presentation.canonical_products or []),
                ambiguity_reason=existing_ambiguity,
            )
            state.decision.grounding_decision = decision
            debug_meta["grounding"] = decision.to_debug_dict()
            debug_meta["grounding_status"] = decision.status
            debug_meta["grounding_safe_action"] = decision.safe_customer_action
            debug_meta["grounding_reasons"] = list(decision.reasons)

            allowed_ids = {str(item).strip() for item in list(decision.allowed_product_ids or []) if str(item).strip()}
            if allowed_ids and decision.status == "grounded":
                grounded_products = [
                    product
                    for product in list(state.presentation.canonical_products or [])
                    if cls._card_identifier(product) in allowed_ids
                ]
                if len(grounded_products) != len(list(state.presentation.canonical_products or [])):
                    state.presentation.canonical_products = grounded_products
                    state.catalog.product_ids = [cls._card_identifier(card) for card in grounded_products]
                    state.retrieval.result_count = len(grounded_products)
                    debug_meta["grounding_filtered_product_count"] = len(grounded_products)
                return

            if existing_ambiguity:
                return

            if decision.safe_customer_action in {"clarify", "no_match", "fallback"}:
                reason = (
                    "grounding_no_match"
                    if decision.safe_customer_action == "no_match"
                    else "grounding_needs_clarification"
                )
                if decision.safe_customer_action == "no_match" and list(state.presentation.canonical_products or []):
                    close_products = list(state.presentation.canonical_products or [])
                    close_ids = [cls._card_identifier(card) for card in close_products if cls._card_identifier(card)]
                    state.decision.ambiguity_reason = ""
                    state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                    state.catalog.product_ids = list(close_ids)
                    state.catalog.query_product_ids = list(close_ids)
                    state.catalog.pagination_has_more = False
                    state.retrieval.result_count = len(close_products)
                    state.retrieval.source = ComponentSource.SQL
                    debug_meta["grounding_blocked_response"] = False
                    debug_meta["catalog_close_match_used"] = True
                    debug_meta["catalog_close_match_count"] = len(close_products)
                    debug_meta["detail_reply_text"] = "I couldn't find an exact match, but here are similar products you might like."
                    debug_meta["detail_carousel_msg"] = "Similar products are shown below."
                    return
                state.decision.ambiguity_reason = reason
                state.presentation.canonical_products = []
                state.catalog.product_ids = []
                state.catalog.query_product_ids = []
                state.catalog.pagination_has_more = False
                state.retrieval.result_count = 0
                if decision.safe_customer_action == "no_match" and dict(plan.required_filters or {}):
                    state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
                    state.knowledge.answer = cls._build_structured_no_match_reply(
                        attribute_filters=dict(plan.required_filters or {}),
                    )
                    state.retrieval.source = ComponentSource.SQL
                    debug_meta["catalog_no_match_answer"] = state.knowledge.answer
                else:
                    state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    state.retrieval.source = ComponentSource.ERROR
                debug_meta["grounding_blocked_response"] = True

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

            if await self._handle_compare_workflow(
                state=state,
                text=text,
                unique_sku_tokens=unique_sku_tokens,
                debug_meta=debug_meta,
                spans=spans,
            ):
                return

            if await self._handle_context_detail_reference_followup(
                state=state,
                detail=detail,
                text=text,
                debug_meta=debug_meta,
                spans=spans,
            ):
                return

            if await self._handle_context_product_followup(
                state=state,
                detail=detail,
                debug_meta=debug_meta,
                spans=spans,
            ):
                return
            if await self._handle_context_related_product_followup(
                state=state,
                detail=detail,
                text=text,
                debug_meta=debug_meta,
                spans=spans,
            ):
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

            if str(state.decision.ambiguity_reason or "").strip() == "structured_no_match":
                candidate_products = list(state.presentation.canonical_products or [])
                candidate_ids = [self._card_identifier(card) for card in candidate_products if self._card_identifier(card)]
                close_match_ids = list(candidate_ids or [str(item).strip() for item in list(product_ids or []) if str(item).strip()])
                if candidate_products or close_match_ids:
                    state.decision.ambiguity_reason = ""
                    state.knowledge.answer = ""
                    state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                    state.catalog.product_ids = list(close_match_ids)
                    state.catalog.query_product_ids = list(close_match_ids)
                    state.catalog.pagination_has_more = False
                    state.retrieval.result_count = max(len(candidate_products), len(close_match_ids))
                    state.retrieval.source = ComponentSource.SQL
                    debug_meta["detail_reply_text"] = "I couldn't find an exact match, but here are similar products you might like."
                    debug_meta["detail_carousel_msg"] = "Similar products are shown below."
                    debug_meta["catalog_no_match_answer"] = debug_meta["detail_reply_text"]
                    debug_meta["catalog_no_match_preserved_product_count"] = max(len(candidate_products), len(close_match_ids))
                else:
                    state.knowledge.answer = self._build_structured_no_match_reply(
                        attribute_filters=dict(getattr(detail, "attribute_filters", {}) or {}),
                    )
                    state.catalog.query_product_ids = []
                    state.catalog.pagination_has_more = False
                    debug_meta["catalog_no_match_answer"] = state.knowledge.answer

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

            await self._handle_detail_workflow(
                state=state,
                detail=detail,
                unique_sku_tokens=unique_sku_tokens,
                text=text,
                debug_meta=debug_meta,
            )

            if (
                state.catalog.query_cache_key
                and (
                    not bool(getattr(detail, "is_detail_request", False))
                    or bool(debug_meta.get("detail_broad_request_as_catalog"))
                )
                and list(state.catalog.query_product_ids or [])
            ):
                unique_products, total_unique_products = product_presentation.dedupe_products_by_master_code(
                    state.presentation.canonical_products,
                    limit=max(len(state.presentation.canonical_products), 1),
                )
                if unique_products:
                    unique_product_ids = [self._card_identifier(card) for card in unique_products]
                    state.catalog.query_product_ids = list(unique_product_ids)
                    state.presentation.canonical_products = list(unique_products)
                    state.catalog.product_ids = list(unique_product_ids)
                    state.retrieval.result_count = max(
                        int(state.retrieval.result_count or 0),
                        int(total_unique_products or 0),
                    )
                    state.catalog.pagination_has_more = bool(total_unique_products > display_limit)
                    debug_meta["catalog_query_product_ids"] = list(unique_product_ids)
                    debug_meta["product_unique_master_count"] = int(total_unique_products)
                    debug_meta["catalog_pagination_has_more"] = bool(state.catalog.pagination_has_more)
                    await self._component_cache.set_json(
                        state.catalog.query_cache_key,
                        {
                            "product_ids": [str(item) for item in unique_product_ids],
                            "source": str(state.retrieval.source.value),
                            "result_count": int(total_unique_products or len(unique_product_ids)),
                            "presentation": "master_representative_v1",
                        },
                        ttl_seconds=300,
                    )
            self._finalize_catalog_products(
                state=state,
                detail=detail,
                display_limit=display_limit,
                debug_meta=debug_meta,
            )
            self._apply_catalog_grounding(
                state=state,
                debug_meta=debug_meta,
            )
