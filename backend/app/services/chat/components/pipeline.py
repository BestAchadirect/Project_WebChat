from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat import Conversation, Message
from app.models.product import Product, StockStatus
from app.models.product_search_projection import ProductSearchProjection
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatResponseMeta,
    KnowledgeSource,
    ProductCard,
)
from app.services.ai.llm_service import llm_service
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.chat import commerce_intents, conversation_state, product_presentation, result_policy, routing_policy
from app.services.chat.components.cache import RedisComponentCache, stable_cache_key
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.field_resolver import FieldDependencyResolver
from app.services.chat.components.registry import ComponentRegistry
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.detail_query_parser import DetailQueryParser
from app.services.chat.detail_response_builder import DetailResponseBuilder
from app.services.chat.product_detail_resolver import ProductDetailResolver
from app.services.chat.recommendation_service import RecommendationService
from app.services.knowledge.retrieval import KnowledgeRetrievalService


@dataclass
class ComponentPipelineResult:
    response: ChatResponse
    detail_mode_triggered: bool
    llm_calls: int
    embedding_calls: int
    external_call_counts: Dict[str, int] = field(default_factory=dict)
    spans: Dict[str, float] = field(default_factory=dict)
    debug: Dict[str, Any] = field(default_factory=dict)
    conversation_state: Optional[Dict[str, Any]] = None


class ComponentPipeline:
    _SMALLTALK_TERMS = {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
    }
    _POLICY_TERMS = {
        "shipping",
        "warranty",
        "refund",
        "return",
        "payment",
        "tax",
        "vat",
        "customs",
        "policy",
        "sample",
        "minimum order",
        "moq",
    }
    _PRODUCT_TERMS = {
        "sku",
        "ring",
        "barbell",
        "labret",
        "clicker",
        "plug",
        "tunnel",
        "color",
        "material",
        "gauge",
        "threading",
        "compare",
        "table",
        "stock",
        "price",
    }
    _ATTRIBUTE_LIST_TERMS = {
        "material": "material",
        "materials": "material",
        "color": "color",
        "colors": "color",
        "gauge": "gauge",
        "gauges": "gauge",
        "threading": "threading",
        "threadings": "threading",
        "type": "jewelry_type",
        "types": "jewelry_type",
    }
    _DETAIL_CLARIFY_FIELDS = {"price", "stock"}
    _KNOWLEDGE_UNAVAILABLE_MESSAGE = (
        "I can share a brief answer right now, but detailed knowledge search is temporarily unavailable."
    )

    def __init__(
        self,
        *,
        db: AsyncSession,
        catalog_search: CatalogProductSearchService,
        knowledge_retrieval: KnowledgeRetrievalService,
        redis_cache: RedisComponentCache,
    ):
        self.db = db
        self._catalog_search = catalog_search
        self._knowledge_retrieval = knowledge_retrieval
        self._redis_cache = redis_cache
        self._field_resolver = FieldDependencyResolver(db=db)
        self._recommendation_service = RecommendationService(db=db, catalog_search=catalog_search)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text or "").strip().lower().split())

    @classmethod
    def _is_smalltalk(cls, text: str) -> bool:
        normalized = cls._normalize_text(text)
        if not normalized:
            return False
        return normalized in cls._SMALLTALK_TERMS

    @staticmethod
    def _is_probable_sku_token(token: str) -> bool:
        cleaned = (token or "").strip().strip(".,!?;:'\"()[]{}<>")
        if not cleaned:
            return False
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,31}", cleaned):
            return False
        has_alpha = any(ch.isalpha() for ch in cleaned)
        has_digit = any(ch.isdigit() for ch in cleaned)
        if not has_alpha:
            return False
        if has_digit:
            return True
        # Without digits, accept only explicit uppercase code-like tokens (e.g. "SKU-ABC").
        return cleaned == cleaned.upper() and any(ch in "._-" for ch in cleaned)

    @classmethod
    def _extract_sku_tokens(cls, text: str) -> List[str]:
        pattern = r"\b[A-Za-z0-9]{2,}(?:[-._][A-Za-z0-9]{1,})+\b"
        found = re.findall(pattern, str(text or ""))
        deduped: List[str] = []
        seen = set()
        for token in found:
            if not cls._is_probable_sku_token(token):
                continue
            key = token.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(token)
        return deduped

    @classmethod
    def _is_knowledge_intent(
        cls,
        *,
        text: str,
        detail_has_filters: bool,
        detail_request: bool,
        sku_tokens: List[str],
    ) -> bool:
        normalized = cls._normalize_text(text)
        if detail_request or detail_has_filters or sku_tokens:
            return False
        if any(term in normalized for term in cls._POLICY_TERMS):
            return True
        if any(term in normalized for term in cls._PRODUCT_TERMS):
            return False
        return normalized.endswith("?")

    @staticmethod
    def _is_compare_requested(text: str) -> bool:
        normalized = text.lower()
        return "compare" in normalized or "vs" in normalized

    @staticmethod
    def _wants_recommendation(text: str) -> bool:
        return commerce_intents.is_recommendation_request(text)

    @staticmethod
    def _is_store_overview_request(
        *,
        text: str,
        detail_has_filters: bool,
        detail_request: bool,
        sku_tokens: List[str],
    ) -> bool:
        return bool(
            commerce_intents.is_store_overview_request(text)
            and not detail_has_filters
            and not detail_request
            and not sku_tokens
        )

    @staticmethod
    def _to_product_card(product) -> ProductCard:
        attrs = dict(product.attributes or {})
        return ProductCard(
            id=product.product_id,
            object_id=product.sku,
            sku=product.sku,
            legacy_sku=[],
            name=product.title,
            description=product.description,
            price=float(product.price),
            currency=product.currency,
            stock_status="in_stock" if product.in_stock else "out_of_stock",
            image_url=product.image_url,
            product_url=product.product_url,
            attributes=attrs,
        )

    @staticmethod
    def _to_meta(
        *,
        query_summary: str,
        source: ComponentSource,
        latency_ms: float,
        llm_calls: int,
        embedding_calls: int,
    ) -> ChatResponseMeta:
        return ChatResponseMeta(
            query_summary=str(query_summary or ""),
            latency_ms=round(float(latency_ms), 2),
            source=source.value,
            llm_calls=int(llm_calls),
            embedding_calls=int(embedding_calls),
        )

    @staticmethod
    def _components_to_map(components) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for component in components:
            raw_type = getattr(component, "type", "")
            key = str(getattr(raw_type, "value", raw_type) or "").strip().lower()
            out[key] = dict(getattr(component, "data", {}) or {})
        return out

    @staticmethod
    def _display_attribute_value(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.islower():
            return " ".join([part.capitalize() for part in text.split(" ") if part])
        return text

    @classmethod
    def _detect_attribute_list_target(cls, text: str) -> str:
        normalized = cls._normalize_text(text)
        if not normalized:
            return ""
        asks_for_list = bool(
            re.search(r"\b(what|which|list|show|available|sell|have|offer|carry)\b", normalized)
            or normalized.endswith("?")
        )
        if not asks_for_list:
            return ""
        for token, target in cls._ATTRIBUTE_LIST_TERMS.items():
            if re.search(rf"\b{re.escape(token)}\b", normalized):
                return target
        return ""

    @classmethod
    def _plan_components(
        cls,
        *,
        user_text: str,
        intent: str,
        product_count: int,
        is_detail_mode: bool,
        is_ambiguous: bool,
    ) -> List[ComponentType]:
        text = cls._normalize_text(user_text)
        intent_norm = cls._normalize_text(intent)

        if not text:
            return [ComponentType.ERROR]

        if is_ambiguous:
            return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]

        if intent_norm in {"knowledge_query", "knowledge", "faq", "off_topic"}:
            return [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]

        wants_reco = commerce_intents.is_recommendation_request(text)
        if intent_norm == "compare_products":
            if product_count <= 0:
                return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
            return [ComponentType.QUERY_SUMMARY, ComponentType.COMPARE]

        components: List[ComponentType] = [ComponentType.QUERY_SUMMARY]

        product_intent = intent_norm.startswith("product") or intent_norm in {
            "browse_products",
            "search_specific",
            "recommend_products",
            "compare_products",
        }
        if product_count <= 0 and product_intent:
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

    async def _load_featured_product_ids(self, *, limit: int = 40) -> List[str]:
        if not hasattr(self.db, "execute"):
            return []
        stmt = (
            select(Product.id)
            .where(Product.is_active.is_(True))
            .order_by(
                case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                case((Product.is_featured.is_(True), 0), else_=1),
                Product.priority.desc(),
                Product.created_at.desc(),
            )
            .limit(max(1, int(limit)))
        )
        try:
            result = await self.db.execute(stmt)
        except Exception:
            return []
        return [str(row[0]) for row in list(result.all() or []) if row and row[0]]

    async def _load_conversation_state(self, *, conversation_id: int) -> Dict[str, Any]:
        if not conversation_id or not hasattr(self.db, "execute"):
            return conversation_state.load_state(None)
        try:
            result = await self.db.execute(
                select(Conversation.state).where(Conversation.id == int(conversation_id)).limit(1)
            )
        except Exception:
            return conversation_state.load_state(None)
        row = result.first()
        raw_state = row[0] if row else None
        return conversation_state.load_state(raw_state)

    @classmethod
    def _top_product_attributes(
        cls,
        *,
        products: Sequence[Any],
        key: str,
        limit: int,
    ) -> List[str]:
        counts: Counter[str] = Counter()
        for product in list(products or []):
            attrs = dict(getattr(product, "attributes", {}) or {})
            if key == "material":
                raw = attrs.get("material") or getattr(product, "material", None)
            else:
                raw = attrs.get(key)
            text = cls._display_attribute_value(str(raw or ""))
            if not text:
                continue
            counts[text] += 1
        return [value for value, _count in counts.most_common(max(1, int(limit)))]

    @classmethod
    def _build_store_overview_reply(
        cls,
        *,
        products: Sequence[Any],
    ) -> str:
        jewelry_types = cls._top_product_attributes(products=products, key="jewelry_type", limit=4)
        materials = cls._top_product_attributes(products=products, key="material", limit=3)
        if jewelry_types and materials:
            return (
                f"We carry products like {', '.join(jewelry_types)} in materials such as "
                f"{', '.join(materials)}. Here are a few options to start with."
            )
        if jewelry_types:
            return f"We carry products like {', '.join(jewelry_types)}. Here are a few options to start with."
        if materials:
            return f"We carry products in materials such as {', '.join(materials)}. Here are a few options to start with."
        return "We carry a range of body jewelry and related products. Here are a few options to start with."

    @classmethod
    def _build_store_overview_follow_ups(
        cls,
        *,
        products: Sequence[Any],
        limit: int = 4,
    ) -> List[str]:
        follow_ups: List[str] = []
        for jewelry_type in cls._top_product_attributes(products=products, key="jewelry_type", limit=3):
            follow_ups.append(f"Show {jewelry_type}")
        for material in cls._top_product_attributes(products=products, key="material", limit=2):
            follow_ups.append(f"Show {material} jewelry")
        deduped: List[str] = []
        seen: set[str] = set()
        for item in follow_ups:
            key = item.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= max(1, int(limit)):
                break
        return deduped

    @classmethod
    def _build_grounded_knowledge_fallback_answer(
        cls,
        *,
        sources: Sequence[KnowledgeSource],
    ) -> str:
        parts: List[str] = []
        for source in list(sources or [])[:2]:
            title = str(getattr(source, "title", "") or "").strip()
            snippet = cls._normalize_text(str(getattr(source, "content_snippet", "") or ""))
            if not snippet:
                continue
            if title:
                parts.append(f"{title}: {snippet}")
            else:
                parts.append(snippet)
        if parts:
            return "Here is what I found: " + " ".join(parts)
        return "I found related information, but I could not format a full answer."

    async def _load_distinct_attribute_values(
        self,
        *,
        target: str,
        attribute_filters: Dict[str, str],
        limit: int = 20,
    ) -> List[str]:
        if not hasattr(self.db, "execute"):
            return []
        projection_cols = {
            "material": ProductSearchProjection.material_norm,
            "color": ProductSearchProjection.color_norm,
            "gauge": ProductSearchProjection.gauge_norm,
            "threading": ProductSearchProjection.threading_norm,
            "jewelry_type": ProductSearchProjection.jewelry_type_norm,
        }
        target_col = projection_cols.get(str(target or "").strip().lower())
        if target_col is None:
            return []

        stmt = select(target_col).where(
            ProductSearchProjection.is_active.is_(True),
            target_col.is_not(None),
            target_col != "",
        )
        for raw_key, raw_value in dict(attribute_filters or {}).items():
            key = str(raw_key or "").strip().lower()
            if key == str(target or "").strip().lower():
                continue
            value = self._normalize_text(str(raw_value or ""))
            if not value:
                continue
            filter_col = projection_cols.get(key)
            if filter_col is None:
                continue
            stmt = stmt.where(filter_col == value)

        stmt = stmt.group_by(target_col).order_by(target_col.asc()).limit(max(1, int(limit)))
        try:
            result = await self.db.execute(stmt)
        except Exception:
            return []
        values: List[str] = []
        seen: set[str] = set()
        for raw in list(result.scalars().all() or []):
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            values.append(self._display_attribute_value(text))
        return values

    async def _load_recent_product_ids_for_image_followup(
        self,
        *,
        conversation_id: int,
        max_messages: int = 8,
        max_ids: int = 20,
    ) -> List[str]:
        if int(conversation_id or 0) <= 0:
            return []
        if not hasattr(self.db, "execute"):
            return []
        stmt = (
            select(Message.product_data)
            .where(
                Message.conversation_id == int(conversation_id),
                Message.role == "assistant",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(max(1, int(max_messages)))
        )
        try:
            result = await self.db.execute(stmt)
        except Exception:
            return []
        for raw_payload in list(result.scalars().all() or []):
            if not isinstance(raw_payload, list) or not raw_payload:
                continue
            deduped_ids: List[str] = []
            seen: set[str] = set()
            for item in raw_payload:
                if not isinstance(item, dict):
                    continue
                product_id = str(item.get("id") or "").strip()
                if not product_id:
                    continue
                key = product_id.lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped_ids.append(product_id)
                if len(deduped_ids) >= max(1, int(max_ids)):
                    break
            if deduped_ids:
                return deduped_ids
        return []

    @classmethod
    def _derive_legacy(
        cls,
        *,
        context: ComponentContext,
        components,
    ) -> Dict[str, Any]:
        mapped = cls._components_to_map(components)
        query_summary = str(mapped.get("query_summary", {}).get("text") or context.query_summary or "").strip()
        user_text = str(context.user_text or "").strip()
        reply_text = "I processed your request."
        carousel_msg = ""
        product_carousel: List[ProductCard] = []
        follow_ups: List[str] = []

        if "error" in mapped:
            reply_text = str(mapped["error"].get("message") or "I could not process this request.")
        elif "clarify" in mapped:
            reply_text = str(mapped["clarify"].get("message") or "Please share more details.")
        elif "knowledge_answer" in mapped:
            reply_text = str(mapped["knowledge_answer"].get("answer") or query_summary)
        elif "compare" in mapped:
            compare_products = list(context.canonical_products or [])
            compared = [cls._to_product_card(item) for item in compare_products]
            product_carousel = compared
            if len(compare_products) >= 2:
                reply_text = f"I found {len(compare_products)} products to compare."
                carousel_msg = "Comparison results are shown below."
            else:
                reply_text = "Please provide two products to compare."
        elif "product_detail" in mapped:
            detail_products = list(context.canonical_products or [])
            product_carousel = [cls._to_product_card(item) for item in detail_products]
            reply_text = str(context.debug.get("detail_reply_text") or "").strip() or query_summary
            carousel_msg = str(context.debug.get("detail_carousel_msg") or "").strip()
            follow_ups.extend(list(context.debug.get("detail_follow_ups") or []))
        elif "product_cards" in mapped:
            if bool(context.debug.get("detail_reply_text")):
                display_products = list(context.canonical_products or [])
            else:
                display_products, _total_unique_products = product_presentation.dedupe_products_by_master_code(
                    context.canonical_products,
                    limit=product_presentation.PRODUCT_DISPLAY_LIMIT,
                )
            if bool(context.debug.get("store_overview_request")):
                reply_text = str(context.debug.get("store_overview_reply") or "").strip()
                if not reply_text:
                    reply_text = cls._build_store_overview_reply(products=display_products)
                follow_ups.extend(list(context.debug.get("store_overview_follow_ups") or []))
            elif bool(context.debug.get("detail_reply_text")):
                reply_text = str(context.debug.get("detail_reply_text") or "").strip()
                carousel_msg = str(context.debug.get("detail_carousel_msg") or "").strip()
                follow_ups.extend(list(context.debug.get("detail_follow_ups") or []))
            elif "recommendations" in mapped or bool(context.debug.get("recommendation_ranked_count")):
                reply_text = product_presentation.build_recommendation_match_reply(
                    attribute_filters=context.attribute_filters,
                )
            else:
                reply_text = product_presentation.build_product_match_reply(
                    attribute_filters=context.attribute_filters,
                )
            product_carousel = [cls._to_product_card(item) for item in display_products]
            if not carousel_msg:
                carousel_msg = "Matching products are shown below."
            if int(context.result_count or 0) > len(product_carousel) and not bool(context.debug.get("store_overview_request")):
                follow_ups.append(
                    product_presentation.build_see_more_follow_up(
                        attribute_filters=context.attribute_filters,
                        user_text=user_text,
                    )
                )

        recommendation_items = list(mapped.get("recommendations", {}).get("items") or [])
        if recommendation_items:
            follow_ups.append("Show recommendations")

        return {
            "reply_text": reply_text,
            "carousel_msg": carousel_msg,
            "product_carousel": product_carousel,
            "follow_up_questions": follow_ups[:5],
        }

    async def _knowledge_answer_once(
        self,
        *,
        question: str,
        sources: List[KnowledgeSource],
        locale: str,
        llm_cache_key: str,
    ) -> tuple[str, bool]:
        cached = await self._redis_cache.get_json(llm_cache_key)
        if isinstance(cached, dict) and str(cached.get("answer", "")).strip():
            return str(cached.get("answer", "")), True

        snippets = "\n".join(
            [
                f"- {source.title}: {source.content_snippet}"
                for source in (sources or [])[:5]
            ]
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Answer strictly from provided context. "
                    "Do not invent products, SKUs, or policies not in context. "
                    "Return JSON with a single key `reply`."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Locale: {locale}\n"
                    f"Question: {question}\n"
                    f"Context:\n{snippets}\n\n"
                    "Respond in JSON."
                ),
            },
        ]
        data = await llm_service.generate_chat_json(
            messages,
            model=getattr(settings, "RAG_ANSWER_MODEL", None) or settings.OPENAI_MODEL,
            temperature=0.2,
            usage_kind="component_knowledge_answer",
        )
        answer = str(data.get("reply", "") or "").strip()
        if not answer:
            answer = self._build_grounded_knowledge_fallback_answer(sources=sources)
        if answer:
            await self._redis_cache.set_json(llm_cache_key, {"answer": answer}, ttl_seconds=120)
        return answer, False

    async def run(
        self,
        *,
        request: ChatRequest,
        conversation_id: int,
        run_id: str,
    ) -> ComponentPipelineResult:
        started = time.perf_counter()
        text = str(request.message or "").strip()
        locale = str(request.locale or "en-US")
        normalized_text = self._normalize_text(text)
        detail = DetailQueryParser.parse(user_text=text, nlu_data={})
        conversation_state_enabled = bool(getattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False))
        state_working: Optional[Dict[str, Any]] = None
        conversation_state_filter_merge_applied = False
        if conversation_state_enabled:
            state_working = await self._load_conversation_state(conversation_id=conversation_id)
        sku_tokens = self._extract_sku_tokens(text)
        unique_sku_tokens = [token for token in dict.fromkeys([str(item).strip() for item in sku_tokens]) if token]
        if conversation_state_enabled and state_working is not None:
            debug_state_version = int(
                state_working.get("version", conversation_state.CONVERSATION_STATE_VERSION)
            )
        else:
            debug_state_version = conversation_state.CONVERSATION_STATE_VERSION
        if conversation_state_enabled and state_working is not None:
            if conversation_state.should_merge_follow_up_filters(
                user_text=text,
                current_filters=detail.attribute_filters,
                sku_token=unique_sku_tokens[0] if unique_sku_tokens else None,
            ):
                merged_filters = conversation_state.merge_filters(
                    detail.attribute_filters,
                    state_working.get("last_attribute_filters", {}),
                )
                detail = replace(detail, attribute_filters=merged_filters)
                conversation_state_filter_merge_applied = True

        route_decision = routing_policy.decide_route(
            text=text,
            detail_has_filters=bool(detail.attribute_filters),
            detail_request=bool(detail.is_detail_request),
            sku_tokens=sku_tokens,
        )
        compare_requested = route_decision.compare_requested
        recommendation_requested = route_decision.recommendation_requested
        store_overview_request = route_decision.store_overview_request
        smalltalk_intent = route_decision.smalltalk_intent
        knowledge_intent = route_decision.knowledge_intent
        intent = route_decision.intent
        source = route_decision.source
        ambiguity_reason = None

        llm_calls = 0
        embedding_calls = 0
        external_call_counts: Dict[str, int] = {}
        spans: Dict[str, float] = {
            "intent_routing_ms": 0.0,
            "db_product_lookup_ms": 0.0,
            "vector_search_ms": 0.0,
            "llm_answer_ms": 0.0,
            "response_build_ms": 0.0,
        }
        debug_meta: Dict[str, Any] = {
            "component_pipeline_enabled": True,
            "component_intent": intent,
            "path_kind": "component_pipeline",
            "image_only_filter_applied": False,
            "image_only_result_count": 0,
            "image_followup_context_used": False,
            "image_followup_context_count": 0,
            "store_overview_request": store_overview_request,
            "conversation_state_enabled": conversation_state_enabled,
            "conversation_state_filter_merge_applied": bool(conversation_state_filter_merge_applied),
            "conversation_state_loaded_version": int(debug_state_version),
            "conversation_state_written": False,
            "detail_requested_fields": list(detail.requested_fields or []),
        }
        if conversation_state_enabled and state_working is not None:
            state_working = conversation_state.apply_intent_update(
                state_working,
                intent=intent,
                refined_query=text,
                attribute_filters=detail.attribute_filters,
            )

        intent_started = time.perf_counter()
        spans["intent_routing_ms"] = (time.perf_counter() - intent_started) * 1000.0

        query_summary = text if text else "Please provide a question."
        selected_components: List[ComponentType] = []
        canonical_products = []
        recommendations = []
        knowledge_sources: List[KnowledgeSource] = []
        knowledge_answer = ""
        result_count = 0
        product_ids: List[Any] = []
        query_embedding: Optional[List[float]] = None
        retrieval_source = source
        handled_attribute_list = False
        attribute_list_target = ""
        display_limit = product_presentation.PRODUCT_DISPLAY_LIMIT
        result_fetch_limit = max(display_limit * 6, 20)

        if smalltalk_intent:
            selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            knowledge_answer = (
                "Hi! Tell me what product you are looking for, for example type, material, gauge, or SKU."
            )
            retrieval_source = ComponentSource.TOOL
        elif compare_requested:
            if len(unique_sku_tokens) < 2:
                ambiguity_reason = "compare_requires_two_skus"
        elif store_overview_request:
            featured_started = time.perf_counter()
            product_ids = await self._load_featured_product_ids(limit=result_fetch_limit)
            spans["db_product_lookup_ms"] += (time.perf_counter() - featured_started) * 1000.0
            result_count = len(product_ids)
            retrieval_source = ComponentSource.SQL
            debug_meta["store_overview_candidate_count"] = int(result_count)
        # Generic image follow-up can reuse latest conversation product context.
        if (
            not smalltalk_intent
            and not ambiguity_reason
            and bool(detail.wants_image)
            and not unique_sku_tokens
            and not bool(detail.attribute_filters)
        ):
            context_started = time.perf_counter()
            product_ids = await self._load_recent_product_ids_for_image_followup(
                conversation_id=conversation_id,
                max_messages=8,
                max_ids=20,
            )
            spans["db_product_lookup_ms"] += (time.perf_counter() - context_started) * 1000.0
            if product_ids:
                result_count = len(product_ids)
                retrieval_source = ComponentSource.SQL
                debug_meta["image_followup_context_used"] = True
                debug_meta["image_followup_context_count"] = int(result_count)
            else:
                ambiguity_reason = "image_request_missing_context"

        if not smalltalk_intent and not knowledge_intent and not ambiguity_reason and not store_overview_request:
            attribute_list_target = self._detect_attribute_list_target(text)
            if (
                attribute_list_target
                and not unique_sku_tokens
                and not bool(detail.wants_image)
            ):
                values = await self._load_distinct_attribute_values(
                    target=attribute_list_target,
                    attribute_filters=detail.attribute_filters,
                    limit=20,
                )
                debug_meta["attribute_list_target"] = attribute_list_target
                debug_meta["attribute_list_values_count"] = int(len(values))
                if values:
                    handled_attribute_list = True
                    result_count = len(values)
                    retrieval_source = ComponentSource.SQL
                    label_map = {
                        "material": "materials",
                        "color": "colors",
                        "gauge": "gauges",
                        "threading": "threading options",
                        "jewelry_type": "jewelry types",
                    }
                    label = label_map.get(attribute_list_target, f"{attribute_list_target} options")
                    preview = ", ".join([str(item) for item in values[:12]])
                    knowledge_answer = f"We currently sell these {label}: {preview}."
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
                    debug_meta["attribute_list_values"] = values
                else:
                    ambiguity_reason = "attribute_list_no_results"

        if not smalltalk_intent and not knowledge_intent and not ambiguity_reason and not handled_attribute_list:
            if product_ids:
                debug_meta["query_id_cache_hit"] = False
                debug_meta["structured_read_mode"] = "history"
                debug_meta["projection_hit"] = False
            else:
                read_mode = "projection" if bool(getattr(settings, "CHAT_PROJECTION_READ_ENABLED", False)) else "eav"
                query_cache_key = stable_cache_key(
                    f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:query_ids",
                    {
                        "q": normalized_text,
                        "locale": locale.lower(),
                        "sku": unique_sku_tokens[0].lower() if unique_sku_tokens else "",
                        "sku_list": [item.lower() for item in unique_sku_tokens[:5]],
                        "compare": bool(compare_requested),
                        "filters": detail.attribute_filters,
                        "catalog_version": str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
                        "read_mode": read_mode,
                        "presentation": "master_dedupe_v1",
                        "fetch_limit": result_fetch_limit,
                    },
                )
                cached_ids_payload = await self._redis_cache.get_json(query_cache_key)
                if isinstance(cached_ids_payload, dict) and isinstance(cached_ids_payload.get("product_ids"), list):
                    product_ids = list(cached_ids_payload.get("product_ids") or [])
                    cached_source = str(cached_ids_payload.get("source") or "sql")
                    retrieval_source = ComponentSource(cached_source) if cached_source in {e.value for e in ComponentSource} else ComponentSource.SQL
                    result_count = int(cached_ids_payload.get("result_count") or 0)
                    debug_meta["query_id_cache_hit"] = True
                    debug_meta["match_tier"] = result_policy.classify_match_tier(
                        structured_found=retrieval_source == ComponentSource.SQL and bool(product_ids),
                        semantic_found=retrieval_source == ComponentSource.VECTOR and bool(product_ids),
                    )
                    if compare_requested and len(unique_sku_tokens) >= 2 and not product_ids:
                        ambiguity_reason = "compare_missing_sku"
                        debug_meta["compare_missing_skus"] = unique_sku_tokens[:5]
                else:
                    debug_meta["query_id_cache_hit"] = False
                    if compare_requested and len(unique_sku_tokens) >= 2:
                        debug_meta["compare_mode"] = "sku_first"
                        compare_started = time.perf_counter()
                        compare_ids: List[Any] = []
                        missing_skus: List[str] = []
                        projection_hits: List[bool] = []
                        for sku_token in unique_sku_tokens[:5]:
                            compare_result, compare_meta = await self._catalog_search.structured_search(
                                sku_token=sku_token,
                                attribute_filters={},
                                limit=1,
                                candidate_cap=int(getattr(settings, "CHAT_STRUCTURED_CANDIDATE_CAP", 300)),
                                catalog_version=str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
                                return_ids_only=True,
                            )
                            projection_hits.append(bool(compare_meta.get("projection_hit", False)))
                            if "structured_read_mode" not in debug_meta:
                                debug_meta["structured_read_mode"] = compare_meta.get("structured_read_mode")
                            ids = list(compare_result.product_ids or [])
                            if ids:
                                compare_ids.append(ids[0])
                            else:
                                missing_skus.append(sku_token)
                        spans["db_product_lookup_ms"] += (time.perf_counter() - compare_started) * 1000.0
                        debug_meta["projection_hit"] = bool(any(projection_hits))
                        if missing_skus:
                            ambiguity_reason = "compare_missing_sku"
                            debug_meta["compare_missing_skus"] = missing_skus
                            product_ids = []
                        else:
                            product_ids = compare_ids
                        retrieval_source = ComponentSource.SQL
                        result_count = len(product_ids)
                    else:
                        structured_started = time.perf_counter()
                        structured_result, structured_meta = await self._catalog_search.structured_search(
                            sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                            attribute_filters=detail.attribute_filters,
                            limit=result_fetch_limit,
                            candidate_cap=int(getattr(settings, "CHAT_STRUCTURED_CANDIDATE_CAP", 300)),
                            catalog_version=str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
                            return_ids_only=True,
                        )
                        spans["db_product_lookup_ms"] += (time.perf_counter() - structured_started) * 1000.0
                        product_ids = list(structured_result.product_ids or [])
                        retrieval_source = ComponentSource.SQL
                        debug_meta["structured_read_mode"] = structured_meta.get("structured_read_mode")
                        debug_meta["projection_hit"] = structured_meta.get("projection_hit")
                        semantic_decision = result_policy.semantic_fallback_decision(
                            intent=intent,
                            attribute_filters=detail.attribute_filters,
                            sku_tokens=unique_sku_tokens,
                            detail_mode=bool(detail.is_detail_request),
                            compare_requested=compare_requested,
                            store_overview_request=store_overview_request,
                        )
                        debug_meta["semantic_fallback_allowed"] = bool(semantic_decision.allow)
                        debug_meta["semantic_fallback_reason"] = semantic_decision.reason

                        if product_ids:
                            result_count = await self._catalog_search.structured_count(
                                sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                                attribute_filters=detail.attribute_filters,
                            )
                            debug_meta["match_tier"] = result_policy.classify_match_tier(
                                structured_found=True,
                                semantic_found=False,
                            )
                        elif (
                            semantic_decision.allow
                            and int(getattr(settings, "CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST", 1)) > 0
                            and not unique_sku_tokens
                        ):
                            try:
                                embed_started = time.perf_counter()
                                embedding = await llm_service.generate_embedding(text)
                                spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                                query_embedding = list(embedding or [])
                                embedding_calls += 1
                                external_call_counts["embedding_query"] = (
                                    int(external_call_counts.get("embedding_query", 0)) + 1
                                )
                                vector_started = time.perf_counter()
                                vector_result = await self._catalog_search.smart_search(
                                    query_embedding=embedding,
                                    candidates=sku_tokens or [text],
                                    limit=result_fetch_limit,
                                )
                                spans["vector_search_ms"] += (time.perf_counter() - vector_started) * 1000.0
                                product_ids = list(vector_result.product_ids or [str(card.id) for card in vector_result.cards])
                                result_count = len(product_ids)
                                retrieval_source = ComponentSource.VECTOR if product_ids else ComponentSource.SQL
                                debug_meta["match_tier"] = result_policy.classify_match_tier(
                                    structured_found=False,
                                    semantic_found=bool(product_ids),
                                )
                                if not product_ids:
                                    ambiguity_reason = "structured_no_match"
                            except Exception as exc:
                                debug_meta["component_vector_fallback_error"] = str(exc)
                                debug_meta["component_vector_fallback_skipped"] = True
                                product_ids = []
                                result_count = 0
                                retrieval_source = ComponentSource.SQL
                                ambiguity_reason = "structured_no_match"
                                debug_meta["match_tier"] = result_policy.classify_match_tier(
                                    structured_found=False,
                                    semantic_found=False,
                                )
                        else:
                            debug_meta["component_vector_fallback_skipped"] = True
                            product_ids = []
                            result_count = 0
                            retrieval_source = ComponentSource.SQL
                            ambiguity_reason = "structured_no_match"
                            debug_meta["match_tier"] = result_policy.classify_match_tier(
                                structured_found=False,
                                semantic_found=False,
                            )

                    await self._redis_cache.set_json(
                        query_cache_key,
                        {
                            "product_ids": [str(item) for item in product_ids],
                            "source": retrieval_source.value,
                            "result_count": result_count,
                        },
                        ttl_seconds=300,
                    )

            selected_components = self._plan_components(
                user_text=text,
                intent=intent,
                product_count=len(product_ids),
                is_detail_mode=bool(detail.is_detail_request),
                is_ambiguous=bool(ambiguity_reason),
            )
            if (
                recommendation_requested
                and product_ids
                and ComponentType.RECOMMENDATIONS not in selected_components
            ):
                selected_components.append(ComponentType.RECOMMENDATIONS)

            resolver_started = time.perf_counter()
            canonical_products, resolver_meta = await self._field_resolver.resolve(
                product_ids=product_ids,
                component_types=selected_components,
                redis_cache=self._redis_cache,
            )
            spans["db_product_lookup_ms"] += (time.perf_counter() - resolver_started) * 1000.0
            debug_meta.update(resolver_meta)
            result_count = max(result_count, len(canonical_products))

            if store_overview_request and canonical_products:
                debug_meta["store_overview_reply"] = self._build_store_overview_reply(products=canonical_products)
                debug_meta["store_overview_follow_ups"] = self._build_store_overview_follow_ups(
                    products=canonical_products,
                    limit=4,
                )

            if detail.wants_image and not bool(detail.is_detail_request):
                debug_meta["image_only_filter_applied"] = True
                canonical_products = [
                    item
                    for item in canonical_products
                    if str(getattr(item, "image_url", "") or "").strip()
                ]
                result_count = len(canonical_products)
                debug_meta["image_only_result_count"] = int(result_count)
                if result_count <= 0:
                    ambiguity_reason = "image_only_no_results"
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    recommendations = []

            if detail.is_detail_request and canonical_products and not recommendation_requested and not compare_requested:
                candidate_cards = [self._to_product_card(item) for item in canonical_products]
                resolution = ProductDetailResolver().resolve_detail_request(
                    candidate_cards=candidate_cards,
                    distance_by_id={str(card.id): 0.0 for card in candidate_cards},
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
                    ambiguity_reason = "detail_request_needs_specific_product"
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    canonical_products = []
                    recommendations = []
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
                    detail_by_id = {str(item.product_id): item for item in canonical_products}
                    canonical_products = [
                        detail_by_id[str(card.id)]
                        for card in list(detail_payload.product_carousel or [])
                        if str(card.id) in detail_by_id
                    ]
                    result_count = len(canonical_products)
                    if canonical_products:
                        selected_components = (
                            [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_DETAIL]
                            if len(canonical_products) == 1
                            else [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                        )
                    else:
                        ambiguity_reason = "detail_no_match"
                        selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                        recommendations = []
                if ambiguity_reason == "detail_request_needs_specific_product":
                    result_count = 0
                elif not canonical_products and ambiguity_reason != "detail_no_match":
                    ambiguity_reason = "detail_no_match"
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    recommendations = []

            if recommendation_requested and canonical_products:
                anchor_products = list(canonical_products[:3])
                anchor_ids = [item.product_id for item in anchor_products]
                recommendation_mode = self._recommendation_service.detect_mode(user_text=text)
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
                            embedding_calls += 1
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
                            expansion_product_ids = [str(card.id) for card in list(complementary_result.cards or [])]
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
                        canonical_products, resolver_meta = await self._field_resolver.resolve(
                            product_ids=merged_ids,
                            component_types=selected_components,
                            redis_cache=self._redis_cache,
                        )
                        spans["db_product_lookup_ms"] += (time.perf_counter() - resolver_started) * 1000.0
                        debug_meta.update(resolver_meta)
                        product_ids = merged_ids
                        debug_meta["recommendation_expand_added_ids"] = int(len(extra_ids))

                ranked = self._recommendation_service.rank_canonical_products(
                    candidates=canonical_products,
                    attribute_filters=detail.attribute_filters,
                    user_text=text,
                    distance_by_id=recommendation_distance_by_id,
                    anchor_products=anchor_products,
                    limit=result_fetch_limit,
                    exclude_product_ids=anchor_ids
                    if (unique_sku_tokens or recommendation_mode == "complementary_items")
                    else None,
                )
                debug_meta.update(ranked.meta)
                if ranked.items:
                    canonical_products = list(ranked.items)
                recommendations = list(canonical_products[:5])

            if compare_requested or bool(detail.is_detail_request):
                display_products = list(canonical_products)
                total_unique_products = len(display_products)
            else:
                display_products, total_unique_products = product_presentation.dedupe_products_by_master_code(
                    canonical_products,
                    limit=display_limit,
                )
            debug_meta["raw_product_row_count"] = int(len(canonical_products))
            debug_meta["product_unique_master_count"] = int(total_unique_products)
            debug_meta["product_display_count"] = int(len(display_products))
            debug_meta["product_overflow_available"] = bool(total_unique_products > len(display_products))
            canonical_products = list(display_products)
            result_count = max(int(result_count or 0), int(total_unique_products))
            if recommendation_requested and not recommendations:
                recommendations = list(canonical_products[:5])
        elif not smalltalk_intent and not knowledge_intent and not handled_attribute_list:
            selected_components = self._plan_components(
                user_text=text,
                intent=intent,
                product_count=0,
                is_detail_mode=bool(detail.is_detail_request),
                is_ambiguous=True,
            )
        elif not smalltalk_intent and knowledge_intent:
            selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            knowledge_error_message = ""
            if int(getattr(settings, "CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST", 1)) > 0:
                try:
                    embed_started = time.perf_counter()
                    embedding = await llm_service.generate_embedding(text)
                    spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                    embedding_calls += 1
                    external_call_counts["embedding_query"] = int(external_call_counts.get("embedding_query", 0)) + 1
                    knowledge_started = time.perf_counter()
                    knowledge_sources = await self._knowledge_retrieval.search(
                        query_text=text,
                        query_embedding=embedding,
                        limit=5,
                        run_id=run_id,
                    )
                    spans["vector_search_ms"] += (time.perf_counter() - knowledge_started) * 1000.0
                except Exception as exc:
                    debug_meta["component_knowledge_search_error"] = str(exc)
                    knowledge_error_message = self._KNOWLEDGE_UNAVAILABLE_MESSAGE
            if not knowledge_error_message:
                llm_cache_key = stable_cache_key(
                    f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:knowledge_answer",
                    {
                        "q": normalized_text,
                        "locale": locale.lower(),
                        "source_ids": [source.source_id for source in knowledge_sources],
                    },
                )
                try:
                    llm_started = time.perf_counter()
                    knowledge_answer, from_cache = await self._knowledge_answer_once(
                        question=text,
                        sources=knowledge_sources,
                        locale=locale,
                        llm_cache_key=llm_cache_key,
                    )
                    spans["llm_answer_ms"] += (time.perf_counter() - llm_started) * 1000.0
                    if not from_cache:
                        llm_calls += 1
                        external_call_counts["llm_answer"] = int(external_call_counts.get("llm_answer", 0)) + 1
                except Exception as exc:
                    debug_meta["component_knowledge_answer_error"] = str(exc)
                    knowledge_error_message = self._KNOWLEDGE_UNAVAILABLE_MESSAGE

            if knowledge_error_message:
                selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.ERROR]
                retrieval_source = ComponentSource.ERROR
                result_count = 0
                debug_meta["component_knowledge_fail_soft"] = True
            else:
                retrieval_source = ComponentSource.KNOWLEDGE
                result_count = len(knowledge_sources)

        context = ComponentContext(
            user_text=text,
            locale=locale,
            intent=intent,
            query_summary=query_summary,
            source=retrieval_source,
            selected_components=selected_components,
            canonical_products=canonical_products,
            recommendations=recommendations,
            knowledge_sources=knowledge_sources,
            knowledge_answer=knowledge_answer,
            result_count=result_count,
            attribute_filters=dict(detail.attribute_filters or {}),
            sku_tokens=list(sku_tokens),
            ambiguity_reason=ambiguity_reason,
            error_message=knowledge_error_message if knowledge_intent else None,
            debug=debug_meta,
        )

        build_started = time.perf_counter()
        components = await ComponentRegistry.build_components(
            component_types=selected_components,
            context=context,
        )
        spans["response_build_ms"] += (time.perf_counter() - build_started) * 1000.0

        legacy = self._derive_legacy(context=context, components=components)
        total_ms = (time.perf_counter() - started) * 1000.0
        meta = self._to_meta(
            query_summary=query_summary,
            source=retrieval_source,
            latency_ms=total_ms,
            llm_calls=llm_calls,
            embedding_calls=embedding_calls,
        )
        response = ChatResponse(
            conversation_id=conversation_id,
            reply_text=str(legacy["reply_text"]),
            carousel_msg=str(legacy["carousel_msg"] or ""),
            product_carousel=list(legacy["product_carousel"] or []),
            follow_up_questions=list(legacy["follow_up_questions"] or []),
            intent=intent,
            sources=knowledge_sources,
            debug={},
            components=components,
            meta=meta,
        )
        conversation_state_payload: Optional[Dict[str, Any]] = None
        if conversation_state_enabled and state_working is not None:
            state_working = conversation_state.apply_retrieval_update(
                state_working,
                product_ids=conversation_state.product_ids_from_cards(response.product_carousel),
                route=intent,
            )
            state_working = conversation_state.apply_response_update(
                state_working,
                requested_fields=detail.requested_fields,
                currency=(
                    str(response.product_carousel[0].currency or "")
                    if list(response.product_carousel or [])
                    else ""
                ),
                route=intent,
                product_ids=conversation_state.product_ids_from_cards(response.product_carousel),
            )
            conversation_state_payload = dict(state_working)
            debug_meta["conversation_state_written"] = True

        debug_meta.update(
            {
                "component_plan": [item.value for item in selected_components],
                "component_count": len(components),
                "embedding_count": embedding_calls,
                "llm_call_count": llm_calls,
                "component_source": retrieval_source.value,
            }
        )
        return ComponentPipelineResult(
            response=response,
            detail_mode_triggered=bool(detail.is_detail_request),
            llm_calls=llm_calls,
            embedding_calls=embedding_calls,
            external_call_counts=external_call_counts,
            spans=spans,
            debug=debug_meta,
            conversation_state=conversation_state_payload,
        )
