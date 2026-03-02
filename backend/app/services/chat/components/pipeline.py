from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat import Message
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
from app.services.chat.components.cache import RedisComponentCache, stable_cache_key
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.field_resolver import FieldDependencyResolver
from app.services.chat.components.planner import OutputPlanner
from app.services.chat.components.registry import ComponentRegistry
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.detail_query_parser import DetailQueryParser
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
        normalized = text.lower()
        return any(token in normalized for token in ("suggest", "recommend", "minimal"))

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
        result_count = int(mapped.get("result_count", {}).get("count") or context.result_count or 0)
        reply_text = "I processed your request."
        carousel_msg = ""
        product_carousel: List[ProductCard] = []
        follow_ups: List[str] = []

        normalized_query_summary = " ".join(query_summary.lower().split())
        normalized_user_text = " ".join(user_text.lower().split())
        should_use_summary_prefix = bool(
            normalized_query_summary
            and normalized_query_summary != normalized_user_text
        )
        summary_prefix = query_summary if should_use_summary_prefix else ""

        if "error" in mapped:
            reply_text = str(mapped["error"].get("message") or "I could not process this request.")
        elif "clarify" in mapped:
            reply_text = str(mapped["clarify"].get("message") or "Please share more details.")
        elif "knowledge_answer" in mapped:
            reply_text = str(mapped["knowledge_answer"].get("answer") or query_summary)
        elif "product_cards" in mapped:
            reply_text = (f"{summary_prefix} " if summary_prefix else "") + f"I found {result_count} matching product(s)."
            product_carousel = [cls._to_product_card(item) for item in context.canonical_products[:10]]
            carousel_msg = "Matching products are shown below."

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
        sku_tokens = self._extract_sku_tokens(text)
        unique_sku_tokens = [token for token in dict.fromkeys([str(item).strip() for item in sku_tokens]) if token]
        compare_requested = self._is_compare_requested(text)
        smalltalk_intent = self._is_smalltalk(text)
        knowledge_intent = self._is_knowledge_intent(
            text=text,
            detail_has_filters=bool(detail.attribute_filters),
            detail_request=bool(detail.is_detail_request),
            sku_tokens=sku_tokens,
        )
        if smalltalk_intent:
            intent = "smalltalk"
            source = ComponentSource.TOOL
        else:
            intent = "knowledge_query" if knowledge_intent else ("search_specific" if sku_tokens else "browse_products")
            source = ComponentSource.KNOWLEDGE if knowledge_intent else ComponentSource.SQL
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
        }

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
        retrieval_source = source
        handled_attribute_list = False
        attribute_list_target = ""

        if smalltalk_intent:
            selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            knowledge_answer = (
                "Hi! Tell me what product you are looking for, for example type, material, gauge, or SKU."
            )
            retrieval_source = ComponentSource.TOOL
        elif compare_requested:
            ambiguity_reason = "compare_not_supported"
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

        if not smalltalk_intent and not knowledge_intent and not ambiguity_reason:
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
                    },
                )
                cached_ids_payload = await self._redis_cache.get_json(query_cache_key)
                if isinstance(cached_ids_payload, dict) and isinstance(cached_ids_payload.get("product_ids"), list):
                    product_ids = list(cached_ids_payload.get("product_ids") or [])
                    cached_source = str(cached_ids_payload.get("source") or "sql")
                    retrieval_source = ComponentSource(cached_source) if cached_source in {e.value for e in ComponentSource} else ComponentSource.SQL
                    result_count = int(cached_ids_payload.get("result_count") or 0)
                    debug_meta["query_id_cache_hit"] = True
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
                            limit=20,
                            candidate_cap=int(getattr(settings, "CHAT_STRUCTURED_CANDIDATE_CAP", 300)),
                            catalog_version=str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
                            return_ids_only=True,
                        )
                        spans["db_product_lookup_ms"] += (time.perf_counter() - structured_started) * 1000.0
                        product_ids = list(structured_result.product_ids or [])
                        retrieval_source = ComponentSource.SQL if product_ids else ComponentSource.VECTOR
                        debug_meta["structured_read_mode"] = structured_meta.get("structured_read_mode")
                        debug_meta["projection_hit"] = structured_meta.get("projection_hit")

                        if product_ids:
                            result_count = await self._catalog_search.structured_count(
                                sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                                attribute_filters=detail.attribute_filters,
                            )
                        elif (
                            int(getattr(settings, "CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST", 1)) > 0
                            and not unique_sku_tokens
                        ):
                            try:
                                embed_started = time.perf_counter()
                                embedding = await llm_service.generate_embedding(text)
                                spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                                embedding_calls += 1
                                external_call_counts["embedding_query"] = (
                                    int(external_call_counts.get("embedding_query", 0)) + 1
                                )
                                vector_started = time.perf_counter()
                                vector_result = await self._catalog_search.smart_search(
                                    query_embedding=embedding,
                                    candidates=sku_tokens or [text],
                                    limit=20,
                                )
                                spans["vector_search_ms"] += (time.perf_counter() - vector_started) * 1000.0
                                product_ids = list(vector_result.product_ids or [str(card.id) for card in vector_result.cards])
                                result_count = len(product_ids)
                                retrieval_source = ComponentSource.VECTOR if product_ids else ComponentSource.SQL
                            except Exception as exc:
                                debug_meta["component_vector_fallback_error"] = str(exc)
                                debug_meta["component_vector_fallback_skipped"] = True
                                product_ids = []
                                result_count = 0
                                retrieval_source = ComponentSource.SQL

                    await self._redis_cache.set_json(
                        query_cache_key,
                        {
                            "product_ids": [str(item) for item in product_ids],
                            "source": retrieval_source.value,
                            "result_count": result_count,
                        },
                        ttl_seconds=300,
                    )

            selected_components = OutputPlanner.plan(
                user_text=text,
                intent=intent,
                sku_count=len(sku_tokens),
                product_count=len(product_ids),
                is_detail_mode=bool(detail.is_detail_request),
                is_ambiguous=bool(ambiguity_reason),
                ambiguity_reason=ambiguity_reason,
            )
            if self._wants_recommendation(text) and ComponentType.RECOMMENDATIONS not in selected_components:
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

            if detail.wants_image:
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

            if ComponentType.RECOMMENDATIONS in selected_components:
                reco_key = stable_cache_key(
                    f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:recommendations",
                    {"q": normalized_text, "base_ids": [str(item.product_id) for item in canonical_products[:10]]},
                )
                cached_reco = await self._redis_cache.get_json(reco_key)
                if isinstance(cached_reco, dict) and isinstance(cached_reco.get("product_ids"), list):
                    id_set = {str(item) for item in list(cached_reco.get("product_ids") or [])}
                    recommendations = [item for item in canonical_products if str(item.product_id) in id_set][:5]
                    debug_meta["recommendation_cache_hit"] = True
                else:
                    recommendations = canonical_products[1:4] if len(canonical_products) > 1 else canonical_products[:3]
                    await self._redis_cache.set_json(
                        reco_key,
                        {"product_ids": [str(item.product_id) for item in recommendations]},
                        ttl_seconds=300,
                    )
                    debug_meta["recommendation_cache_hit"] = False
        elif not smalltalk_intent and not knowledge_intent and not handled_attribute_list:
            selected_components = OutputPlanner.plan(
                user_text=text,
                intent=intent,
                sku_count=len(sku_tokens),
                product_count=0,
                is_detail_mode=bool(detail.is_detail_request),
                is_ambiguous=True,
                ambiguity_reason=ambiguity_reason,
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
        )
