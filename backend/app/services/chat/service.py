from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.config import settings
from app.models.chat import AppUser, Conversation, Message, MessageRole
from app.models.product import Product
from app.models.product_attribute import AttributeDefinition, ProductAttributeValue
from app.models.qa_log import QALog, QAStatus
from app.prompts.system_prompts import rag_answer_prompt
from app.schemas.chat import (
    ChatComponent,
    ChatContext,
    ChatRequest,
    ChatResponse,
    ChatResponseMeta,
    KnowledgeSource,
    ProductCard,
)
from app.services.ai.llm_service import llm_service
from app.services.currency_service import currency_service
from app.services.catalog.attributes_service import eav_service
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.ai.response_renderer import ResponseRenderer
from app.services.semantic_cache_service import semantic_cache_service
from app.services.chat.agentic.orchestrator import AgentOrchestrator
from app.services.chat.detail_query_parser import DetailQueryParser
from app.services.chat.detail_response_builder import DetailResponseBuilder
from app.services.chat.intent_router import IntentRouter
from app.services.chat.knowledge_context import KnowledgeContextAssembler
from app.services.chat.product_context import ProductContextAssembler
from app.services.chat.product_detail_resolver import ProductDetailResolver
from app.services.chat.response_consistency import ResponseConsistencyPolicy
from app.services.chat.retrieval_gate import RetrievalGate
from app.services.chat.agentic.tool_registry import AgentToolRegistry
from app.services.chat.components import ComponentPipeline, redis_component_cache
from app.services.chat.hot_cache import build_cache_key, build_feature_flags_hash, hot_response_cache
from app.services.knowledge.retrieval import KnowledgeRetrievalService
from app.utils.debug_log import debug_log as _debug_log

logger = get_logger(__name__)


class EmbeddingSkippedReason(str, Enum):
    NOT_NEEDED = "not_needed"
    STRUCTURED_RESULTS_FOUND = "structured_results_found"
    BUDGET_EXCEEDED = "budget_exceeded"
    DISABLED_BY_ROUTE = "disabled_by_route"


class ExternalBudgetExceededReason(str, Enum):
    EXTERNAL_CALL_BUDGET = "external_call_budget"
    EXTERNAL_TIMEOUT = "external_timeout"
    EXTERNAL_CONNECTIVITY = "external_connectivity"
    LLM_CALL_CAP = "llm_call_cap"


class ChatService:
    """Chat orchestration (intent -> retrieval -> response)."""
    _last_cache_stats_log_ts: float = 0.0

    _FOLLOW_UP_STOPWORDS = {
        "a",
        "an",
        "and",
        "are",
        "ask",
        "for",
        "from",
        "get",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "show",
        "tell",
        "the",
        "to",
        "try",
        "we",
        "with",
        "you",
        "your",
    }
    _FOLLOW_UP_PRODUCT_TERMS = {
        "accessories",
        "attachment",
        "attachments",
        "barbell",
        "browse",
        "code",
        "detail",
        "details",
        "gauge",
        "image",
        "images",
        "instock",
        "labret",
        "material",
        "price",
        "product",
        "products",
        "ring",
        "rings",
        "see",
        "similar",
        "sku",
        "stock",
    }
    _FOLLOW_UP_POLICY_TERMS = {
        "customs",
        "delivery",
        "exchange",
        "minimum",
        "moq",
        "order",
        "payment",
        "policy",
        "refund",
        "return",
        "sample",
        "samples",
        "shipping",
        "warranty",
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self._catalog_search = CatalogProductSearchService(db=self.db)
        self._knowledge_retrieval = KnowledgeRetrievalService(db=self.db, log_event=self._log_event)
        self._knowledge_context = KnowledgeContextAssembler(self._knowledge_retrieval)
        self._response_renderer = ResponseRenderer()

    @staticmethod
    def _feature_flags_snapshot() -> Dict[str, Any]:
        return {
            "chat_hot_cache_enabled": bool(getattr(settings, "CHAT_HOT_CACHE_ENABLED", True)),
            "chat_sql_first_enabled": bool(getattr(settings, "CHAT_SQL_FIRST_ENABLED", True)),
            "chat_projection_read_enabled": bool(getattr(settings, "CHAT_PROJECTION_READ_ENABLED", False)),
            "chat_projection_dual_write_enabled": bool(getattr(settings, "CHAT_PROJECTION_DUAL_WRITE_ENABLED", True)),
            "chat_structured_query_cache_enabled": bool(
                getattr(settings, "CHAT_STRUCTURED_QUERY_CACHE_ENABLED", True)
            ),
            "chat_nlu_heuristic_threshold": float(getattr(settings, "CHAT_NLU_HEURISTIC_THRESHOLD", 0.85)),
            "chat_external_call_budget": int(getattr(settings, "CHAT_EXTERNAL_CALL_BUDGET", 3)),
            "chat_external_call_retry_max": int(getattr(settings, "CHAT_EXTERNAL_CALL_RETRY_MAX", 1)),
            "chat_external_call_fail_fast_seconds": float(
                getattr(settings, "CHAT_EXTERNAL_CALL_FAIL_FAST_SECONDS", 3.5)
            ),
            "chat_vector_top_k": int(getattr(settings, "CHAT_VECTOR_TOP_K", 12)),
            "chat_cross_sell_mode": str(getattr(settings, "CHAT_CROSS_SELL_MODE", "off")),
            "chat_max_history_tokens": int(getattr(settings, "CHAT_MAX_HISTORY_TOKENS", 1200)),
            "chat_hard_max_llm_calls_per_request": int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0)),
            "chat_hard_max_embeddings_per_request": int(
                getattr(settings, "CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST", 1)
            ),
            "chat_strict_retrieval_separation_enabled": bool(
                getattr(settings, "CHAT_STRICT_RETRIEVAL_SEPARATION_ENABLED", False)
            ),
            "chat_component_buckets_enabled": bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False)),
            "chat_component_buckets_shadow_mode": bool(
                getattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
            ),
            "chat_component_buckets_require_components": bool(
                getattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
            ),
            "chat_redis_cache_enabled": bool(getattr(settings, "CHAT_REDIS_CACHE_ENABLED", False)),
            "chat_catalog_version": str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
            "chat_prompt_version": str(getattr(settings, "CHAT_PROMPT_VERSION", "v1")),
            "openai_timeout_seconds": float(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 12.0)),
            "openai_max_retries": int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
            "nlu_fast_path_enabled": bool(getattr(settings, "NLU_FAST_PATH_ENABLED", True)),
        }

    @classmethod
    def _config_fingerprint(cls) -> Dict[str, Any]:
        snapshot = cls._feature_flags_snapshot()
        serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=True)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        return {"hash": digest, "flags": snapshot}

    @staticmethod
    def _estimated_tokens(value: str) -> int:
        if not value:
            return 0
        return max(1, int(len(str(value)) / 4))

    @classmethod
    def _trim_history_for_llm(cls, history: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
        if not history:
            return []
        limit = max(32, int(max_tokens or 0))
        kept: List[Dict[str, Any]] = []
        consumed = 0
        for item in reversed(history):
            content = str(item.get("content") or "")
            token_cost = cls._estimated_tokens(content) + 8
            if consumed + token_cost > limit:
                continue
            kept.append(item)
            consumed += token_cost
        kept.reverse()
        return kept

    @staticmethod
    def _build_hot_cache_payload(response: ChatResponse) -> Dict[str, Any]:
        return {
            "reply_text": response.reply_text,
            "carousel_msg": response.carousel_msg,
            "product_carousel": [item.dict() for item in list(response.product_carousel or [])],
            "follow_up_questions": list(response.follow_up_questions or []),
            "intent": response.intent,
            "sources": [item.dict() for item in list(response.sources or [])],
            "view_button_text": response.view_button_text,
            "material_label": response.material_label,
            "jewelry_type_label": response.jewelry_type_label,
            "components": [item.dict() for item in list(response.components or [])],
            "meta": (
                response.meta.dict() if isinstance(response.meta, ChatResponseMeta) else response.meta
            ),
        }

    @staticmethod
    def _response_from_hot_cache_payload(*, conversation_id: int, payload: Dict[str, Any]) -> ChatResponse:
        products = [ProductCard(**item) for item in list(payload.get("product_carousel", []) or [])]
        sources = [KnowledgeSource(**item) for item in list(payload.get("sources", []) or [])]
        components = [ChatComponent(**item) for item in list(payload.get("components", []) or [])]
        raw_meta = payload.get("meta")
        meta: ChatResponseMeta | Dict[str, Any] | None = None
        if isinstance(raw_meta, dict):
            try:
                meta = ChatResponseMeta(**raw_meta)
            except Exception:
                meta = dict(raw_meta)
        return ChatResponse(
            conversation_id=conversation_id,
            reply_text=str(payload.get("reply_text") or ""),
            carousel_msg=str(payload.get("carousel_msg") or ""),
            product_carousel=products,
            follow_up_questions=list(payload.get("follow_up_questions", []) or []),
            intent=str(payload.get("intent") or "rag_strict"),
            sources=sources,
            view_button_text=str(payload.get("view_button_text") or "View Product Details"),
            material_label=str(payload.get("material_label") or "Material"),
            jewelry_type_label=str(payload.get("jewelry_type_label") or "Jewelry Type"),
            components=components,
            meta=meta,
        )

    def _log_cache_stats_if_needed(self, *, run_id: str, debug_meta: Dict[str, Any]) -> None:
        interval = max(5, int(getattr(settings, "CHAT_CACHE_LOG_INTERVAL_SECONDS", 60)))
        now = time.time()
        if now - float(self.__class__._last_cache_stats_log_ts or 0.0) < interval:
            return
        self.__class__._last_cache_stats_log_ts = now
        hot_stats = hot_response_cache.stats()
        structured_stats = self._catalog_search.structured_cache_stats()
        debug_meta["hot_cache_stats"] = hot_stats
        debug_meta["structured_query_cache_stats"] = structured_stats
        self._log_event(
            run_id=run_id,
            location="chat_service.cache.stats",
            data={
                "hot_cache": hot_stats,
                "structured_query_cache": structured_stats,
            },
        )

    def _maybe_store_hot_cache(self, *, cache_key: Optional[str], response: ChatResponse) -> None:
        if not cache_key:
            return
        if not bool(getattr(settings, "CHAT_HOT_CACHE_ENABLED", True)):
            return
        if not hasattr(self.db, "execute"):
            return
        payload = self._build_hot_cache_payload(response)
        hot_response_cache.set(cache_key, payload)

    @staticmethod
    def _new_latency_spans() -> Dict[str, Any]:
        return {
            "total_ms": 0.0,
            "intent_routing_ms": 0.0,
            "detail_mode_triggered": False,
            "detail_query_parser_ms": 0.0,
            "retrieval_gate_ms": 0.0,
            "vector_search_ms": 0.0,
            "db_product_lookup_ms": 0.0,
            "projection_lookup_ms": 0.0,
            "tickets_service_ms": 0.0,
            "llm_calls_count": 0,
            "llm_parse_ms": 0.0,
            "llm_answer_ms": 0.0,
            "response_build_ms": 0.0,
        }

    @staticmethod
    def _add_latency_span(spans: Dict[str, Any], key: str, elapsed_ms: float) -> None:
        current = float(spans.get(key, 0.0) or 0.0)
        spans[key] = current + max(0.0, float(elapsed_ms))

    def _merge_catalog_metrics_into_spans(self, spans: Dict[str, Any]) -> None:
        metrics = getattr(self._catalog_search, "last_metrics", {}) or {}
        vector_ms = float(metrics.get("vector_search_ms", 0.0) or 0.0)
        db_ms = float(metrics.get("db_product_lookup_ms", 0.0) or 0.0)
        self._add_latency_span(spans, "vector_search_ms", vector_ms)
        self._add_latency_span(spans, "db_product_lookup_ms", db_ms)

    def _build_latency_payload(
        self,
        *,
        spans: Dict[str, Any],
        total_started: float,
        detail_mode_triggered: bool,
        token_usage: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload = dict(spans or {})
        payload["total_ms"] = (time.perf_counter() - total_started) * 1000.0
        payload["detail_mode_triggered"] = bool(detail_mode_triggered)
        by_call = []
        if isinstance(token_usage, dict):
            raw_calls = token_usage.get("by_call")
            if isinstance(raw_calls, list):
                by_call = raw_calls
        llm_textual_calls = 0
        for call in by_call:
            kind = str((call or {}).get("kind", "")).strip().lower()
            if kind.startswith("embedding"):
                continue
            llm_textual_calls += 1
        payload["llm_calls_count"] = int(llm_textual_calls)

        rounded: Dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, bool):
                rounded[key] = value
            elif isinstance(value, (int, float)):
                if key == "llm_calls_count":
                    rounded[key] = int(value)
                else:
                    rounded[key] = round(float(value), 2)
            else:
                rounded[key] = value
        return rounded

    async def _finalize_with_latency(
        self,
        *,
        conversation_id: int,
        user_text: str,
        response: ChatResponse,
        token_usage: Optional[Dict[str, Any]],
        channel: Optional[str],
        run_id: str,
        debug_meta: Dict[str, Any],
        spans: Dict[str, Any],
        total_started: float,
        detail_mode_triggered: bool,
    ) -> ChatResponse:
        retrieval_meta = debug_meta.get("retrieval_gate") if isinstance(debug_meta, dict) else None
        route = str(getattr(response, "intent", "") or (debug_meta.get("route") if isinstance(debug_meta, dict) else "") or "")
        raw_follow_ups = list(response.follow_up_questions or [])
        filtered_follow_ups = self._filter_follow_up_questions(
            questions=raw_follow_ups,
            user_text=user_text,
            route=route,
            has_products=bool(response.product_carousel),
            retrieval_gate=retrieval_meta if isinstance(retrieval_meta, dict) else None,
            limit=5,
        )
        if raw_follow_ups != filtered_follow_ups and isinstance(debug_meta, dict):
            debug_meta["follow_up_filter"] = {
                "before_count": len(raw_follow_ups),
                "after_count": len(filtered_follow_ups),
            }
        response.follow_up_questions = filtered_follow_ups

        latency_payload = self._build_latency_payload(
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_triggered,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
        )
        debug_meta["latency_spans"] = latency_payload
        response.debug = dict(response.debug or {})
        response.debug.update(debug_meta)
        response.debug["latency_spans"] = latency_payload
        self._log_event(
            run_id=run_id,
            location="chat_service.latency_spans",
            data=latency_payload,
        )
        return await self._finalize_response(
            conversation_id=conversation_id,
            user_text=user_text,
            response=response,
            token_usage=token_usage,
            channel=channel,
        )

    def _log_latency_error(
        self,
        *,
        run_id: str,
        debug_meta: Dict[str, Any],
        spans: Dict[str, Any],
        total_started: float,
        detail_mode_triggered: bool,
        token_usage: Optional[Dict[str, Any]],
        error: Exception,
    ) -> None:
        latency_payload = self._build_latency_payload(
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_triggered,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
        )
        debug_meta["latency_spans"] = latency_payload
        debug_meta["latency_error"] = str(error)
        self._log_event(
            run_id=run_id,
            location="chat_service.latency_spans.error",
            data={
                "latency_spans": latency_payload,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        lowered = text.lower()
        lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered).strip()
        return lowered

    @classmethod
    def _keyword_tokens(cls, text: str) -> set[str]:
        if not text:
            return set()
        lowered = str(text).lower()
        lowered = lowered.replace("in-stock", "instock").replace("in stock", "instock")
        parts = re.findall(r"[a-z0-9]+", lowered)
        return {
            token
            for token in parts
            if len(token) >= 3 and token not in cls._FOLLOW_UP_STOPWORDS
        }

    @classmethod
    def _is_follow_up_relevant(
        cls,
        *,
        question: str,
        user_text: str,
        route: str,
        has_products: bool,
        use_products: bool,
        use_knowledge: bool,
        is_policy_intent: bool,
    ) -> bool:
        if not question:
            return False

        route_norm = str(route or "").strip().lower()
        if route_norm == "fallback_general":
            return False
        if route_norm == "detail_mode":
            return True

        question_tokens = cls._keyword_tokens(question)
        user_tokens = cls._keyword_tokens(user_text)
        if not question_tokens:
            return False

        if question_tokens & user_tokens:
            return True

        question_lower = str(question).strip().lower()
        has_product_signal = bool(question_tokens & cls._FOLLOW_UP_PRODUCT_TERMS)
        has_policy_signal = bool(question_tokens & cls._FOLLOW_UP_POLICY_TERMS)

        if has_products and (question_lower.startswith("see more ") or question_lower.startswith("show ")):
            return True

        user_has_product_signal = bool(user_tokens & cls._FOLLOW_UP_PRODUCT_TERMS)
        if use_products and has_product_signal and (has_products or user_has_product_signal):
            return True

        user_has_policy_signal = bool(user_tokens & cls._FOLLOW_UP_POLICY_TERMS)
        if use_knowledge and has_policy_signal and (is_policy_intent or user_has_policy_signal):
            return True

        return False

    @classmethod
    def _filter_follow_up_questions(
        cls,
        *,
        questions: List[str],
        user_text: str,
        route: str,
        has_products: bool,
        retrieval_gate: Optional[Dict[str, Any]],
        limit: int = 5,
    ) -> List[str]:
        if not questions:
            return []

        gate = retrieval_gate if isinstance(retrieval_gate, dict) else {}
        use_products = bool(gate.get("use_products", has_products))
        use_knowledge = bool(gate.get("use_knowledge", not use_products))
        is_policy_intent = bool(gate.get("is_policy_intent", False))

        deduped: List[str] = []
        seen: set[str] = set()
        for raw in questions:
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(text)

        kept: List[str] = []
        for question in deduped:
            if cls._is_follow_up_relevant(
                question=question,
                user_text=user_text,
                route=route,
                has_products=has_products,
                use_products=use_products,
                use_knowledge=use_knowledge,
                is_policy_intent=is_policy_intent,
            ):
                kept.append(question)
            if len(kept) >= max(1, int(limit)):
                break
        return kept

    @staticmethod
    def _normalize_jewelry_type(value: Optional[str]) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    @staticmethod
    def _merge_product_attrs(
        base_attrs: Optional[Dict[str, Any]],
        eav_attrs: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        attrs = dict(base_attrs or {})
        if eav_attrs:
            for key, value in eav_attrs.items():
                if value is None:
                    continue
                attrs[key] = value
        return attrs

    def _infer_primary_jewelry_type(
        self,
        *,
        products: List[ProductCard],
        query_text: str,
    ) -> Optional[str]:
        for p in products:
            attrs = p.attributes or {}
            jt = attrs.get("jewelry_type") or attrs.get("type")
            if isinstance(jt, str) and jt.strip():
                return jt.strip()
        return self._infer_jewelry_type_filter(query_text)

    def _build_cross_sell_query(self, jewelry_type: str) -> Optional[str]:
        if not jewelry_type:
            return None
        key = self._normalize_jewelry_type(jewelry_type)
        mapping = {
            "barbells": "barbell replacement balls ends spikes attachments",
            "circularbarbells": "barbell replacement balls ends spikes attachments",
            "labrets": "labret tops ends threadless attachments",
            "ballclosurerings": "replacement balls beads closures",
            "rings": "replacement balls beads closures",
            "captivebeadrings": "replacement balls beads closures",
        }
        return mapping.get(key)

    def _build_cross_sell_label(self, jewelry_type: str) -> Optional[str]:
        if not jewelry_type:
            return None
        key = self._normalize_jewelry_type(jewelry_type)
        label_map = {
            "barbells": "Barbell attachments",
            "circularbarbells": "Barbell attachments",
            "labrets": "Labret tops",
            "ballclosurerings": "Ring beads",
            "rings": "Ring beads",
            "captivebeadrings": "Ring beads",
        }
        return label_map.get(key)

    def _filter_cross_sell_products(
        self,
        *,
        products: List[ProductCard],
        exclude_type: Optional[str],
        exclude_ids: set[str],
        limit: int,
    ) -> List[ProductCard]:
        if not products:
            return []
        exclude_norm = self._normalize_jewelry_type(exclude_type)
        filtered: List[ProductCard] = []
        for p in products:
            pid = str(p.id)
            if pid in exclude_ids:
                continue
            attrs = p.attributes or {}
            jt = attrs.get("jewelry_type") or attrs.get("type")
            if exclude_norm and self._normalize_jewelry_type(jt) == exclude_norm:
                continue
            filtered.append(p)
            if len(filtered) >= limit:
                break
        return filtered



    @staticmethod
    def _is_english_language(reply_language: str) -> bool:
        lang = (reply_language or "").strip().lower()
        return lang.startswith("en") or "english" in lang

    async def _localize_ui_texts(
        self,
        *,
        reply_language: str,
        items: Dict[str, str],
        run_id: str,
    ) -> Dict[str, str]:
        if not items:
            return {}
        if self._is_english_language(reply_language):
            return items
        if not bool(getattr(settings, "UI_LOCALIZATION_ENABLED", True)):
            return items
        if max(0, int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0))) > 0:
            return items

        localized = await llm_service.localize_ui_strings(
            items=items,
            reply_language=reply_language,
            model=getattr(settings, "UI_LOCALIZATION_MODEL", None),
            max_tokens=int(getattr(settings, "UI_LOCALIZATION_MAX_TOKENS", 220)),
            temperature=float(getattr(settings, "UI_LOCALIZATION_TEMPERATURE", 0.1)),
        )
        self._log_event(
            run_id=run_id,
            location="chat_service.ui_localization",
            data={"reply_language": reply_language, "keys": list(items.keys())},
        )
        return localized

    async def _localize_ui_text(
        self,
        *,
        reply_language: str,
        text: str,
        run_id: str,
    ) -> str:
        localized = await self._localize_ui_texts(
            reply_language=reply_language,
            items={"text": text},
            run_id=run_id,
        )
        return localized.get("text", text)

    async def _get_follow_up_questions(self, *, reply_language: str, run_id: str) -> List[str]:
        base = {
            "browse_products": "Browse products",
            "check_sku_price": "Check a SKU price",
            "shipping_policies": "Shipping & policies",
        }
        localized = await self._localize_ui_texts(
            reply_language=reply_language,
            items=base,
            run_id=run_id,
        )
        return [
            localized.get("browse_products", base["browse_products"]),
            localized.get("check_sku_price", base["check_sku_price"]),
            localized.get("shipping_policies", base["shipping_policies"]),
        ]

    async def _localize_price_sentence(
        self,
        *,
        sku: str,
        amount: str,
        currency: str,
        reply_language: str,
        run_id: str,
    ) -> str:
        base = f"The price of {sku} is {amount} {currency}."
        localized = await self._localize_ui_text(
            reply_language=reply_language,
            text=base,
            run_id=run_id,
        )
        if sku not in localized or amount not in localized or currency not in localized:
            return base
        return localized

    @staticmethod
    def _is_no_match_reply_text(text: str) -> bool:
        return ResponseConsistencyPolicy.is_no_match_reply_text(text)

    async def _ensure_reply_consistency_with_products(
        self,
        *,
        reply_data: Dict[str, Any],
        has_products: bool,
        reply_language: str,
        run_id: str,
    ) -> Dict[str, Any]:
        return await ResponseConsistencyPolicy.ensure_consistent_reply(
            reply_data=reply_data,
            has_products=has_products,
            localize_text=lambda text: self._localize_ui_text(
                reply_language=reply_language,
                text=text,
                run_id=run_id,
            ),
        )

    @classmethod
    def _extract_sku_like_tokens(cls, text: str) -> List[str]:
        raw = re.findall(r"\b[A-Za-z0-9]{2,}(?:[-._][A-Za-z0-9]{1,})+\b", str(text or ""))
        deduped: List[str] = []
        seen: set[str] = set()
        for token in raw:
            if not cls._is_probable_sku_token(token):
                continue
            norm = str(token).strip().lower()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            deduped.append(token)
        return deduped

    def _enforce_llm_sku_guard(
        self,
        *,
        reply_data: Dict[str, Any],
        product_cards: List[ProductCard],
    ) -> tuple[Dict[str, Any], bool]:
        if not product_cards:
            return reply_data, False
        reply_text = str((reply_data or {}).get("reply") or "")
        mentioned = self._extract_sku_like_tokens(reply_text)
        if not mentioned:
            return reply_data, False
        allowed = {str(card.sku or "").strip().lower() for card in product_cards if str(card.sku or "").strip()}
        unknown = [token for token in mentioned if str(token).strip().lower() not in allowed]
        if not unknown:
            return reply_data, False
        guarded = dict(reply_data or {})
        guarded["reply"] = f"I found {len(product_cards)} matching products."
        return guarded, True

    @staticmethod
    def _embedding_failure_reply_text(*, use_products: bool, use_knowledge: bool) -> str:
        if use_products and use_knowledge:
            return "I'm having trouble reaching search right now. Please try again in a moment."
        if use_products:
            return "I'm having trouble searching products right now. Please try again in a moment."
        return "I'm having trouble searching my knowledge base right now. Please try again in a moment."

    async def _build_embedding_fail_fast_response(
        self,
        *,
        conversation_id: int,
        user_text: str,
        reply_language: str,
        target_currency: str,
        debug_meta: Dict[str, Any],
        use_products: bool,
        use_knowledge: bool,
    ) -> ChatResponse:
        reply_text = self._embedding_failure_reply_text(
            use_products=use_products,
            use_knowledge=use_knowledge,
        )
        return await self._response_renderer.render(
            conversation_id=conversation_id,
            route="fallback_general",
            reply_data={
                "reply": reply_text,
                "carousel_hint": "",
                "recommended_questions": [],
            },
            product_carousel=[],
            follow_up_questions=[],
            sources=[],
            debug=debug_meta,
            reply_language=reply_language,
            target_currency=target_currency,
            user_text=user_text,
            apply_polish=False,
        )

    @staticmethod
    def _build_route_fallback_text(
        *,
        route_kind: str,
        reason: str,
    ) -> str:
        route = str(route_kind or "").strip().lower()
        if route in {"detail_mode", "search_specific", "browse_products", "product"}:
            return "I can only provide a basic product result right now while search is temporarily limited."
        if route in {"knowledge_query", "rag_strict", "knowledge"}:
            return "I can share a brief answer right now, but detailed knowledge search is temporarily unavailable."
        if route in {"vague", "clarify"}:
            return "Could you share a bit more detail so I can narrow this down accurately?"
        if reason == ExternalBudgetExceededReason.EXTERNAL_CALL_BUDGET.value:
            return "I reached my call budget for this request. Please try a shorter follow-up."
        return "I'm having trouble completing that request right now. Please try again in a moment."

    async def _build_route_fallback_response(
        self,
        *,
        conversation_id: int,
        route_kind: str,
        reason: str,
        user_text: str,
        reply_language: str,
        target_currency: str,
        debug_meta: Dict[str, Any],
        product_carousel: Optional[List[ProductCard]] = None,
    ) -> ChatResponse:
        reply_text = self._build_route_fallback_text(route_kind=route_kind, reason=reason)
        follow_ups: List[str] = []
        if str(route_kind).lower() in {"vague", "clarify"}:
            follow_ups = ["Share product type, material, or SKU to continue."]
        return await self._response_renderer.render(
            conversation_id=conversation_id,
            route="fallback_general",
            reply_data={
                "reply": reply_text,
                "carousel_hint": "Limited product result shown." if product_carousel else "",
                "recommended_questions": follow_ups,
            },
            product_carousel=list(product_carousel or []),
            follow_up_questions=follow_ups,
            sources=[],
            debug=debug_meta,
            reply_language=reply_language,
            target_currency=target_currency,
            user_text=user_text,
            apply_polish=False,
        )

    def _format_language_instruction(self, *, language: Optional[str], locale: Optional[str]) -> str:
        default_locale = str(getattr(settings, "DEFAULT_LOCALE", "en-US") or "en-US")
        language = (language or "").strip()
        locale = (locale or "").strip()
        if language and locale:
            if locale.lower() in language.lower():
                return language
            return f"{language} ({locale})"
        if language:
            return language
        if locale:
            return locale
        return default_locale

    def _heuristic_nlu_fast_path(self, *, user_text: str, locale: Optional[str]) -> tuple[Optional[Dict[str, Any]], float]:
        if not bool(getattr(settings, "NLU_FAST_PATH_ENABLED", True)):
            return None, 0.0
        text = str(user_text or "").strip()
        if len(text) < 3:
            return None, 0.0

        detail_guess = DetailQueryParser.parse(user_text=text, nlu_data={})
        sku_token = self._extract_sku(text)
        explicit_product_signal = bool(
            sku_token
            or detail_guess.attribute_filters
            or self._infer_jewelry_type_filter(text)
        )
        if not explicit_product_signal:
            return None, 0.0

        normalized_locale = str(locale or "").strip() or "en-US"
        intent = "search_specific" if (sku_token or detail_guess.is_detail_request) else "browse_products"
        confidence = 0.6
        if sku_token:
            confidence = 0.99
        elif detail_guess.is_detail_request:
            confidence = 0.92
        elif detail_guess.attribute_filters:
            confidence = 0.88
        fast_path = {
            "language": "English",
            "locale": normalized_locale,
            "intent": intent,
            "show_products": True,
            "currency": "",
            "refined_query": text,
            "product_code": sku_token or "",
            "requested_fields": list(detail_guess.requested_fields),
            "attribute_filters": dict(detail_guess.attribute_filters),
            "wants_image": bool(detail_guess.wants_image),
            "nlu_fast_path": True,
            "nlu_heuristic_confidence": confidence,
        }
        return fast_path, confidence

    @staticmethod
    def _looks_vague_query(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return True
        if len(normalized.split()) <= 2:
            return True
        vague_terms = {"something", "anything", "stuff", "maybe", "ideas", "help me choose"}
        return any(term in normalized for term in vague_terms)

    @staticmethod
    def _is_connectivity_error(exc: Exception) -> bool:
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        signals = ("timeout", "connection", "connect", "dns", "network", "unreachable", "reset")
        if any(signal in name for signal in signals):
            return True
        return any(signal in msg for signal in signals)

    @staticmethod
    def _is_llm_textual_call(call_name: str) -> bool:
        normalized = str(call_name or "").strip().lower()
        return normalized in {"nlu", "llm_answer", "answer_polish", "ui_localization", "agentic_llm"}

    async def _run_external_call(
        self,
        *,
        external_state: Dict[str, Any],
        call_name: str,
        call_factory,
        run_id: str,
        debug_meta: Dict[str, Any],
    ) -> Any:
        hard_llm_cap = max(0, int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0)))
        is_llm_call = self._is_llm_textual_call(call_name)
        if is_llm_call and hard_llm_cap > 0:
            current_llm_calls = int(external_state.get("llm_count", 0))
            if current_llm_calls >= hard_llm_cap:
                external_state["budget_exceeded_reason"] = ExternalBudgetExceededReason.LLM_CALL_CAP.value
                raise RuntimeError("llm call cap exceeded")

        budget = max(1, int(getattr(settings, "CHAT_EXTERNAL_CALL_BUDGET", 3)))
        if int(external_state.get("count", 0)) >= budget:
            external_state["budget_exceeded_reason"] = ExternalBudgetExceededReason.EXTERNAL_CALL_BUDGET.value
            raise RuntimeError("external call budget exceeded")

        external_state["count"] = int(external_state.get("count", 0)) + 1
        if is_llm_call:
            external_state["llm_count"] = int(external_state.get("llm_count", 0)) + 1
        by_name = external_state.setdefault("by_name", {})
        by_name[call_name] = int(by_name.get(call_name, 0)) + 1
        timeout_seconds = max(0.1, float(getattr(settings, "CHAT_EXTERNAL_CALL_FAIL_FAST_SECONDS", 3.5)))
        retry_max = max(0, int(getattr(settings, "CHAT_EXTERNAL_CALL_RETRY_MAX", 1)))
        retries_used = 0
        last_error: Optional[Exception] = None

        for attempt in range(retry_max + 1):
            try:
                call_started = time.perf_counter()
                result = await asyncio.wait_for(call_factory(), timeout=timeout_seconds)
                elapsed_ms = (time.perf_counter() - call_started) * 1000.0
                if elapsed_ms > float(external_state.get("slowest_call_ms", 0.0)):
                    external_state["slowest_call_ms"] = round(float(elapsed_ms), 2)
                    external_state["slowest_call_name"] = call_name
                external_state["retries_used"] = int(external_state.get("retries_used", 0)) + retries_used
                return result
            except asyncio.TimeoutError as exc:
                last_error = exc
                retries_used += 1
                if attempt >= retry_max:
                    external_state["budget_exceeded_reason"] = ExternalBudgetExceededReason.EXTERNAL_TIMEOUT.value
                    raise
            except Exception as exc:
                last_error = exc
                if self._is_connectivity_error(exc):
                    debug_meta["network_error_type"] = type(exc).__name__
                    retries_used += 1
                    if attempt < retry_max:
                        continue
                    external_state["budget_exceeded_reason"] = ExternalBudgetExceededReason.EXTERNAL_CONNECTIVITY.value
                raise

        if last_error:
            raise last_error
        raise RuntimeError("external call failed")

    async def _run_nlu(
        self,
        *,
        user_text: str,
        history: List[Dict[str, str]] = None,
        locale: Optional[str],
        run_id: str,
        external_state: Dict[str, Any],
        debug_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run unified NLU for language, intent, and currency."""
        if not user_text or len(user_text.strip()) < 3:
            return {
                "language": "English",
                "locale": "en-US",
                "intent": "knowledge_query",
                "show_products": False,
                "currency": "",
                "requested_fields": [],
                "attribute_filters": {},
                "wants_image": False,
            }

        fast_path, confidence = self._heuristic_nlu_fast_path(user_text=user_text, locale=locale)
        threshold = float(getattr(settings, "CHAT_NLU_HEURISTIC_THRESHOLD", 0.85))
        hard_llm_cap = max(0, int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0)))
        if hard_llm_cap == 1:
            if isinstance(fast_path, dict):
                debug_meta["nlu_fast_path_forced_by_llm_cap"] = True
                return fast_path
            normalized_locale = str(locale or "").strip() or "en-US"
            debug_meta["nlu_deterministic_fallback"] = True
            return {
                "language": "English",
                "locale": normalized_locale,
                "intent": "knowledge_query",
                "show_products": False,
                "currency": "",
                "refined_query": str(user_text or "").strip(),
                "product_code": "",
                "requested_fields": [],
                "attribute_filters": {},
                "wants_image": False,
                "nlu_fast_path": False,
                "nlu_heuristic_confidence": round(float(confidence), 3),
            }

        if isinstance(fast_path, dict) and float(confidence) >= threshold:
            self._log_event(
                run_id=run_id,
                location="chat_service.nlu.fast_path",
                data={
                    "intent": fast_path.get("intent"),
                    "show_products": fast_path.get("show_products"),
                    "requested_fields": fast_path.get("requested_fields", []),
                    "attribute_filters": fast_path.get("attribute_filters", {}),
                    "confidence": round(float(confidence), 3),
                    "threshold": round(float(threshold), 3),
                },
            )
            return fast_path

        supported = currency_service.supported_currencies()
        data = await self._run_external_call(
            external_state=external_state,
            call_name="nlu",
            call_factory=lambda: llm_service.run_nlu(
                user_message=user_text,
                history=history,
                locale=locale,
                supported_currencies=supported,
                model=getattr(settings, "NLU_MODEL", None),
                max_tokens=int(getattr(settings, "NLU_MAX_TOKENS", 250)),
            ),
            run_id=run_id,
            debug_meta=debug_meta,
        )
        if not isinstance(data, dict):
            data = {}

        raw_fields = data.get("requested_fields")
        if not isinstance(raw_fields, list):
            data["requested_fields"] = []
        else:
            data["requested_fields"] = [str(item).strip().lower() for item in raw_fields if str(item).strip()]

        raw_filters = data.get("attribute_filters")
        if not isinstance(raw_filters, dict):
            data["attribute_filters"] = {}
        else:
            clean_filters: Dict[str, str] = {}
            for key, value in raw_filters.items():
                clean_key = str(key or "").strip().lower()
                clean_val = str(value or "").strip()
                if clean_key and clean_val:
                    clean_filters[clean_key] = clean_val
            data["attribute_filters"] = clean_filters

        data["wants_image"] = bool(data.get("wants_image", False))
        data["nlu_heuristic_confidence"] = round(float(confidence), 3)

        self._log_event(
            run_id=run_id,
            location="chat_service.nlu.run",
            data=data,
        )
        return data

    async def _resolve_reply_language(self, *, nlu_data: Dict[str, Any], user_text: str, locale: Optional[str], run_id: str) -> str:
        mode = str(getattr(settings, "CHAT_LANGUAGE_MODE", "auto") or "auto").lower()
        default_locale = str(getattr(settings, "DEFAULT_LOCALE", "en-US") or "en-US")
        locale = str(locale or "").strip() or None
        
        if mode == "fixed":
            return str(getattr(settings, "FIXED_REPLY_LANGUAGE", "") or "").strip() or default_locale
        
        if mode == "locale" and locale:
            return locale

        # auto: use NLU result
        language = nlu_data.get("language")
        loc = nlu_data.get("locale")
        reply_language = self._format_language_instruction(language=language, locale=loc)
        
        if not reply_language or reply_language.lower() in {"unknown", "none"}:
            reply_language = locale or default_locale
            
        return reply_language

    async def _resolve_target_currency(self, *, nlu_data: Dict[str, Any], user_text: str) -> str:
        """Resolve the target currency using NLU and heuristics."""
        default_display = (
            getattr(settings, "PRICE_DISPLAY_CURRENCY", None)
            or getattr(settings, "BASE_CURRENCY", None)
            or "USD"
        )
        
        # 1. From NLU
        nlu_currency = str(nlu_data.get("currency") or "").strip().upper()
        if nlu_currency and currency_service.supports(nlu_currency):
            return nlu_currency
            
        # 2. Heuristic fallback
        heuristic = currency_service.extract_requested_currency(user_text)
        if heuristic and currency_service.supports(heuristic):
            return heuristic
            
        return default_display.upper()

    def _build_hot_cache_lookup_key(
        self,
        *,
        text: str,
        locale: Optional[str],
        currency: str,
        channel: str,
    ) -> tuple[str, Dict[str, Any]]:
        config_fingerprint = self._config_fingerprint()
        feature_flags_hash = build_feature_flags_hash(config_fingerprint["flags"])
        cache_key = build_cache_key(
            text=text,
            locale=str(locale or getattr(settings, "DEFAULT_LOCALE", "en-US")),
            currency=str(currency or ""),
            channel=str(channel or "widget"),
            catalog_version=str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
            feature_flags_hash=feature_flags_hash,
            prompt_version=str(getattr(settings, "CHAT_PROMPT_VERSION", "v1")),
            cache_version=str(getattr(settings, "CHAT_HOT_CACHE_VERSION", "v1")),
        )
        return cache_key, config_fingerprint

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

    def _extract_sku(self, text: str) -> Optional[str]:
        if not text:
            return None
        explicit = re.search(
            r"\bsku\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9._-]{1,31})\b",
            text,
            flags=re.IGNORECASE,
        )
        if explicit:
            candidate = str(explicit.group(1) or "").strip()
            if self._is_probable_sku_token(candidate):
                return candidate.lower()
        for candidate in re.findall(r"\b([A-Za-z0-9]{2,}(?:[-._][A-Za-z0-9]{1,})+)\b", text):
            normalized = str(candidate or "").strip()
            if self._is_probable_sku_token(normalized):
                return normalized.lower()
        return None

    @staticmethod
    def _clean_code_candidate(token: str) -> str:
        return (token or "").strip(".,!?;:'\"()[]{}<>")

    @classmethod
    def _looks_like_code(cls, token: str) -> bool:
        if not token:
            return False
        t = token.strip()
        if " " in t:
            return False
        if len(t) < 3 or len(t) > 32:
            return False
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", t):
            return False
        has_digit = any(c.isdigit() for c in t)
        has_sep = any(c in "._-" for c in t)
        if has_sep and not has_digit and not cls._is_probable_sku_token(t):
            return False
        is_all_upper = t.isupper()
        return has_digit or has_sep or (is_all_upper and len(t) <= 10)

    async def _cheap_sku_precheck(self, *, user_text: str, limit: int = 3) -> tuple[Optional[str], List[ProductCard]]:
        text = str(user_text or "").strip()
        if not text:
            return None, []
        candidates: List[str] = []
        sku = self._extract_sku(text)
        if sku:
            candidates.append(self._clean_code_candidate(sku))
        for token in re.split(r"\s+", text):
            clean = self._clean_code_candidate(token)
            if self._looks_like_code(clean):
                candidates.append(clean)
        deduped = [item for item in dict.fromkeys(candidates) if item]
        for candidate in deduped[:3]:
            try:
                cards = await self._search_products_by_exact_sku(sku=candidate, limit=max(1, int(limit)))
            except Exception:
                return None, []
            if cards:
                return candidate, cards
        return None, []

    def _extract_code_candidates(self, *, query: str, extracted_code: Optional[str]) -> List[str]:
        candidates: List[str] = []
        if extracted_code:
            clean = self._clean_code_candidate(extracted_code)
            if self._looks_like_code(clean):
                candidates.append(clean)
        sku = self._extract_sku(query)
        if sku and self._looks_like_code(sku):
            candidates.append(sku)
        if query and self._looks_like_code(query):
            candidates.append(query.strip())
        for token in re.split(r"\s+", query or ""):
            clean = self._clean_code_candidate(token)
            if self._looks_like_code(clean):
                candidates.append(clean)
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _is_question_like(text: str) -> bool:
        if not text:
            return False
        lowered = text.strip().lower()
        if "?" in lowered:
            return True
        starters = (
            "who", "what", "when", "where", "why", "how",
            "can", "do", "does", "did", "is", "are", "should", "could", "would", "will",
        )
        return lowered.startswith(starters)

    @staticmethod
    def _is_complex_query(text: str) -> bool:
        if not text:
            return False
        word_count = len(re.findall(r"\b\w+\b", text))
        if word_count >= 14:
            return True
        if text.count("?") > 1:
            return True
        lowered = text.lower()
        if any(sep in lowered for sep in (" and ", " or ", " also ", ";", " as well as ")):
            return True
        return False

    @staticmethod
    def _count_policy_topics(text: str) -> int:
        if not text:
            return 0
        lowered = text.lower()
        topics = [
            "shipping", "delivery", "return", "refund", "exchange", "warranty",
            "payment", "discount", "tax", "customs", "duty", "wholesale",
            "minimum order", "moq", "sample", "custom", "backorder", "lead time",
            "cancellation", "cancel", "order status", "policy",
        ]
        hits: set[str] = set()
        for topic in topics:
            if " " in topic:
                if topic in lowered:
                    hits.add(topic)
            else:
                if re.search(rf"\b{re.escape(topic)}\b", lowered):
                    hits.add(topic)
        return len(hits)

    def _infer_jewelry_type_filter(self, text: str) -> Optional[str]:
        if not text:
            return None
        lowered = text.lower()
        if "labret" in lowered:
            return "Labrets"
        if "ball closure ring" in lowered or re.search(r"\bbcr\b", lowered):
            return "Ball Closure Rings"
        if "circular barbell" in lowered:
            return "Circular Barbells"
        if "belly clip" in lowered or "fake belly" in lowered:
            return "Illusion Clips"
        if "fake plug" in lowered:
            return "Fake Plugs"
        if "barbell" in lowered or "industrial" in lowered:
            return "Barbells"
        return None

    async def _get_product_category_overview(self, limit: int = 6) -> List[str]:
        stmt = (
            select(ProductAttributeValue.value, func.count(func.distinct(ProductAttributeValue.product_id)))
            .join(AttributeDefinition, ProductAttributeValue.attribute_id == AttributeDefinition.id)
            .join(Product, Product.id == ProductAttributeValue.product_id)
            .where(AttributeDefinition.name == "jewelry_type")
            .where(Product.is_active.is_(True))
            .where(ProductAttributeValue.value.isnot(None))
            .group_by(ProductAttributeValue.value)
            .order_by(func.count(func.distinct(ProductAttributeValue.product_id)).desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        categories: List[str] = []
        for value, _count in rows:
            if value:
                categories.append(str(value).strip())
        return categories

    async def _search_products_by_exact_sku(
        self,
        *,
        sku: str,
        limit: int,
    ) -> List[ProductCard]:
        if not sku:
            return []
        stmt = (
            select(Product)
            .where(func.lower(Product.sku) == sku.lower())
            .where(Product.is_active.is_(True))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        products = result.scalars().all()
        attr_map = await eav_service.get_product_attributes(self.db, [p.id for p in products])
        cards: List[ProductCard] = []
        for p in products:
            cards.append(self._product_to_card(p, attr_map.get(p.id)))
        return cards

    def _log_event(self, *, run_id: str, location: str, data: Dict[str, Any]) -> None:
        _debug_log(
            {
                "sessionId": "debug-session",
                "runId": run_id,
                "hypothesisId": "RAG",
                "location": location,
                "message": location,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }
        )

    @staticmethod
    def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if not dt:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def is_conversation_active(self, conversation: Optional[Conversation]) -> bool:
        if conversation is None:
            return False

        now = datetime.now(timezone.utc)
        started_at = self._ensure_utc(conversation.started_at)
        last_message_at = self._ensure_utc(conversation.last_message_at) or started_at

        idle_minutes = int(getattr(settings, "CONVERSATION_IDLE_TIMEOUT_MINUTES", 30) or 0)
        hard_cap_hours = int(getattr(settings, "CONVERSATION_HARD_CAP_HOURS", 24) or 0)

        if idle_minutes > 0 and last_message_at:
            if last_message_at < (now - timedelta(minutes=idle_minutes)):
                return False

        if hard_cap_hours > 0 and started_at:
            if started_at < (now - timedelta(hours=hard_cap_hours)):
                return False

        return True

    @staticmethod
    def _is_agentic_channel_enabled(channel: Optional[str]) -> bool:
        if not bool(getattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)):
            return False
        allowed_raw = str(getattr(settings, "AGENTIC_ALLOWED_CHANNELS", "") or "")
        allowed = {part.strip().lower() for part in allowed_raw.split(",") if part.strip()}
        if not allowed:
            return True
        return str(channel or "").strip().lower() in allowed

    async def get_user(self, user_id: str) -> Optional[AppUser]:
        stmt = select(AppUser).where(AppUser.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_conversation_for_user(
        self,
        user: AppUser,
        conversation_id: int,
    ) -> Optional[Conversation]:
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_conversation(
        self,
        user: AppUser,
        conversation_id: Optional[int] = None,
    ) -> Optional[Conversation]:
        if conversation_id:
            conversation = await self.get_conversation_for_user(user, conversation_id)
            if self.is_conversation_active(conversation):
                return conversation

        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        latest = result.scalar_one_or_none()
        if self.is_conversation_active(latest):
            return latest
        return None

    async def get_or_create_user(
        self,
        user_id: str,
        name: str | None = None,
        email: str | None = None,
    ) -> AppUser:
        stmt = select(AppUser).where(AppUser.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            # Best-effort update
            if name and not user.customer_name:
                user.customer_name = name
            if email and not user.email:
                user.email = email
            self.db.add(user)
            await self.db.commit()
            return user

        user = AppUser(id=user_id, customer_name=name, email=email)
        self.db.add(user)
        try:
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except IntegrityError:
            # Concurrent requests can race on first insert; fetch the winner row.
            await self.db.rollback()
            retry = await self.db.execute(stmt)
            existing = retry.scalar_one_or_none()
            if existing is None:
                raise
            if name and not existing.customer_name:
                existing.customer_name = name
            if email and not existing.email:
                existing.email = email
            self.db.add(existing)
            await self.db.commit()
            return existing

    async def get_or_create_conversation(
        self,
        user: AppUser,
        conversation_id: Optional[int],
    ) -> Conversation:
        if conversation_id:
            stmt = select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()
            if self.is_conversation_active(existing):
                return existing

        conversation = Conversation(user_id=user.id)
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def save_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        product_data: List[ProductCard] | None = None,
        token_usage: Dict[str, Any] | None = None,
        commit: bool = True,
        touch_conversation: bool = True,
    ) -> Message:
        if product_data:
            # Ensure UUIDs are converted to strings for JSON serialization
            data_json = []
            for p in product_data:
                d = p.dict()
                if 'id' in d and d['id']:
                    d['id'] = str(d['id'])
                data_json.append(d)
        else:
            data_json = None
            
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            product_data=data_json,
            token_usage=token_usage,
        )
        self.db.add(msg)
        if touch_conversation:
            await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(last_message_at=func.now())
            )
        if commit:
            await self.db.commit()
        return msg

    async def _finalize_response(
        self,
        *,
        conversation_id: int,
        user_text: str,
        response: ChatResponse,
        token_usage: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> ChatResponse:
        qa_status = QAStatus.SUCCESS
        if response.intent == "fallback_general" or "don't have enough information" in response.reply_text.lower():
            qa_status = QAStatus.FALLBACK

        qa_log = QALog(
            question=user_text,
            answer=response.reply_text,
            sources=[
                {
                    "source_id": s.source_id,
                    "chunk_id": s.chunk_id,
                    "title": s.title,
                    "relevance": s.relevance,
                }
                for s in response.sources
            ],
            status=qa_status,
            token_usage=token_usage,
            channel=channel,
        )
        qa_log_id: Optional[str] = None

        try:
            await self.save_message(
                conversation_id,
                MessageRole.USER,
                user_text,
                commit=False,
                touch_conversation=False,
            )
            await self.save_message(
                conversation_id,
                MessageRole.ASSISTANT,
                response.reply_text,
                product_data=response.product_carousel,
                token_usage=token_usage,
                commit=False,
                touch_conversation=False,
            )
            await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(last_message_at=func.now())
            )
            await self.db.flush()

            try:
                async with self.db.begin_nested():
                    self.db.add(qa_log)
                    await self.db.flush()
                    if qa_log.id:
                        qa_log_id = str(qa_log.id)
            except Exception as e:
                logger.error(f"Failed to log QA event: {e}")

            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        response.qa_log_id = qa_log_id
        return response

    async def submit_feedback(self, *, qa_log_id: UUID, feedback: int) -> Optional[QALog]:
        stmt = select(QALog).where(QALog.id == qa_log_id)
        result = await self.db.execute(stmt)
        qa_log = result.scalar_one_or_none()
        if qa_log is None:
            return None
        if feedback not in (-1, 1):
            raise ValueError("feedback must be -1 or 1")
        qa_log.user_feedback = int(feedback)
        qa_log.feedback_at = datetime.utcnow()
        self.db.add(qa_log)
        await self.db.commit()
        await self.db.refresh(qa_log)
        return qa_log

    async def get_history(self, conversation_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        msgs = result.scalars().all()
        return [
            {
                "role": m.role, 
                "content": m.content,
                "product_data": m.product_data,
                "created_at": m.created_at,
            } for m in reversed(msgs)
        ]

    async def smart_product_search(
        self,
        query: str,
        query_embedding: List[float],
        limit: int = 10,
        run_id: Optional[str] = None,
        extracted_code: Optional[str] = None,
    ) -> Tuple[List[ProductCard], List[float], Optional[float], Dict[str, float]]:
        candidates = self._extract_code_candidates(query=query, extracted_code=extracted_code)
        result = await self._catalog_search.smart_search(
            query_embedding=query_embedding,
            candidates=candidates,
            limit=limit,
        )
        if result.best_distance == 0.0 and result.cards and candidates:
            logger.info(f"Smart Search: Found exact/group match for '{candidates[0]}'")
        return result.cards, result.distances, result.best_distance, result.distance_by_id

    def _product_to_card(
        self,
        product: Product,
        eav_attrs: Optional[Dict[str, Any]] = None,
    ) -> ProductCard:
        attrs = self._merge_product_attrs(product.attributes, eav_attrs)
        search_text = str(getattr(product, "search_text", "") or "").lower()

        if not str(attrs.get("material") or "").strip():
            inferred_material = self._catalog_search._infer_from_search_text(
                search_text=search_text,
                token_map=self._catalog_search._MATERIAL_FALLBACK_TOKENS,
            )
            if inferred_material:
                attrs["material"] = inferred_material

        if not str(attrs.get("jewelry_type") or attrs.get("type") or "").strip():
            inferred_type = self._catalog_search._infer_from_search_text(
                search_text=search_text,
                token_map=self._catalog_search._JEWELRY_TYPE_FALLBACK_TOKENS,
            )
            if inferred_type:
                attrs["jewelry_type"] = inferred_type

        return ProductCard(
            id=product.id,
            object_id=product.object_id,
            sku=product.sku,
            legacy_sku=product.legacy_sku or [],
            name=product.name,
            description=product.description,
            price=product.price,
            currency=product.currency,
            stock_status=product.stock_status,
            image_url=product.image_url,
            product_url=product.product_url,
            attributes=attrs,
        )

    async def search_products(
        self,
        query_embedding: List[float],
        limit: int = 10,
        run_id: Optional[str] = None,
    ) -> Tuple[List[ProductCard], List[float], Optional[float], Dict[str, float]]:
        candidate_multiplier = max(1, int(getattr(settings, "PRODUCT_SEARCH_CANDIDATE_MULTIPLIER", 3)))
        result = await self._catalog_search.vector_search(
            query_embedding=query_embedding,
            limit=limit,
            candidate_multiplier=candidate_multiplier,
        )
        product_cards = result.cards
        distance_by_id = result.distance_by_id
        best_distance = result.best_distance
        distances = result.distances

        for idx, card in enumerate(product_cards[:3]):
            distance = distance_by_id.get(str(card.id))

            # #region agent log
            if run_id and distance is not None:
                try:
                    _debug_log(
                        {
                            "sessionId": "debug-session",
                            "runId": run_id,
                            "hypothesisId": "HP",
                            "location": "chat_service.search_products:top_result",
                            "message": "top product",
                            "data": {
                                "rank": idx + 1,
                                "product_id": str(card.id),
                                "name": card.name,
                                "distance": float(distance),
                                "threshold": settings.PRODUCT_DISTANCE_THRESHOLD,
                            },
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                except Exception:
                    pass
            # #endregion

        return product_cards, distances, best_distance, distance_by_id

    async def synthesize_answer(
        self,
        question: str,
        sources: List[KnowledgeSource],
        reply_language: str,
        history: List[Dict[str, str]] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, str]:
        if not sources:
            msg = await self._localize_ui_text(
                reply_language=reply_language,
                text=(
                    "I don't have enough information in my knowledge base to answer that yet. "
                    "Try asking another question or rephrasing."
                ),
                run_id=run_id or "synthesize_answer",
            )
            return {"reply": msg, "carousel_hint": ""}

        product_context = []
        if history:
            for msg in reversed(history):
                if msg.get("role") == "assistant" and msg.get("product_data"):
                    products = msg["product_data"]
                    summary = ", ".join([f"{p.get('name')} (SKU: {p.get('sku')})" for p in products[:5]])
                    product_context.append(f"Previously shown products: {summary}")

        history_snippets = "\n".join(product_context)
        
        context = "\n\n".join(
            [
                f"ID: {s.source_id}\nTITLE: {s.title}\nTEXT: {s.content_snippet}"
                for s in sources[: min(5, len(sources))]
            ]
        )
        
        if history_snippets:
            context = f"History Context:\n{history_snippets}\n\nSearch Context:\n{context}"
        messages = [
            {
                "role": "system",
                "content": rag_answer_prompt(reply_language),
            },
        ]
        
        # Insert last 5 messages for context
        if history:
            # Format history for LLM (only role and content)
            history_clean = [{"role": m["role"], "content": m["content"]} for m in history]
            messages.extend(history_clean)
            
        messages.append({"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"})
        try:
            answer_model = getattr(settings, "RAG_ANSWER_MODEL", None) or settings.OPENAI_MODEL
            data = await llm_service.generate_chat_json(
                messages,
                model=answer_model,
                temperature=0.2,
                usage_kind="rag_answer",
            )
            return {
                "reply": str(data.get("reply", "")),
                "carousel_hint": str(data.get("carousel_hint", "")),
                "recommended_questions": data.get("recommended_questions", []),
            }
        except Exception as e:
            logger.error(f"LLM response generation failed: {e}")
            msg = await self._localize_ui_text(
                reply_language=reply_language,
                text="I'm having trouble generating an answer right now. Please try again.",
                run_id=run_id or "synthesize_answer",
            )
            return {"reply": msg, "carousel_hint": "", "recommended_questions": []}

    async def _run_component_pipeline(
        self,
        *,
        request: ChatRequest,
        conversation_id: int,
        run_id: str,
    ):
        pipeline = ComponentPipeline(
            db=self.db,
            catalog_search=self._catalog_search,
            knowledge_retrieval=self._knowledge_retrieval,
            redis_cache=redis_component_cache,
        )
        return await pipeline.run(
            request=request,
            conversation_id=conversation_id,
            run_id=run_id,
        )


    async def process_chat(self, req: ChatRequest, channel: Optional[str] = None) -> ChatResponse:
        total_started = time.perf_counter()
        spans = self._new_latency_spans()

        run_id = f"chat-{int(time.time() * 1000)}"
        channel = channel or "widget"
        default_display_currency = (
            getattr(settings, "PRICE_DISPLAY_CURRENCY", None)
            or getattr(settings, "BASE_CURRENCY", None)
            or "USD"
        )
        heuristic_currency = (
            currency_service.extract_requested_currency(req.message or "") or str(default_display_currency).upper()
        )
        hot_cache_key, config_fingerprint = self._build_hot_cache_lookup_key(
            text=req.message or "",
            locale=req.locale,
            currency=heuristic_currency,
            channel=channel,
        )
        debug_meta: Dict[str, Any] = {
            "run_id": run_id,
            "route": "rag_strict",
            "channel": channel,
            "config_fingerprint": config_fingerprint,
            "openai_timeout_seconds": float(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 12.0)),
            "openai_max_retries": int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
            "llm_calls_enforced": max(0, int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0))) > 0,
        }
        llm_service.begin_token_tracking()

        text = req.message or ""
        detail_mode_enabled = False
        external_state: Dict[str, Any] = {
            "count": 0,
            "llm_count": 0,
            "retries_used": 0,
            "budget_exceeded_reason": "",
            "slowest_call_ms": 0.0,
            "slowest_call_name": "",
            "by_name": {},
        }

        def _apply_external_debug() -> None:
            debug_meta["external_call_count"] = int(external_state.get("count", 0))
            debug_meta["llm_call_count"] = int(external_state.get("llm_count", 0))
            debug_meta["external_call_retries_used"] = int(external_state.get("retries_used", 0))
            debug_meta["external_call_counts"] = dict(external_state.get("by_name", {}))
            if external_state.get("budget_exceeded_reason"):
                debug_meta["external_call_budget_exceeded_reason"] = str(external_state["budget_exceeded_reason"])

        async def _finalize_and_cache(response: ChatResponse, token_usage: Optional[Dict[str, Any]]) -> ChatResponse:
            _apply_external_debug()
            finalized = await self._finalize_with_latency(
                conversation_id=conversation.id,
                user_text=text,
                response=response,
                token_usage=token_usage,
                channel=channel,
                run_id=run_id,
                debug_meta=debug_meta,
                spans=spans,
                total_started=total_started,
                detail_mode_triggered=detail_mode_enabled,
            )
            self._maybe_store_hot_cache(cache_key=hot_cache_key, response=finalized)
            self._log_cache_stats_if_needed(run_id=run_id, debug_meta=debug_meta)
            return finalized

        try:
            # 1) Minimal validation only
            user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
            conversation = await self.get_or_create_conversation(user, req.conversation_id)

            # 2) Hot cache before history, NLU, embedding, retrieval
            debug_meta["hot_cache_hit"] = False
            if bool(getattr(settings, "CHAT_HOT_CACHE_ENABLED", True)):
                hot_payload = hot_response_cache.get(hot_cache_key)
                if isinstance(hot_payload, dict):
                    debug_meta["hot_cache_hit"] = True
                    cached_response = self._response_from_hot_cache_payload(
                        conversation_id=conversation.id,
                        payload=hot_payload,
                    )
                    token_usage = llm_service.consume_token_usage()
                    _apply_external_debug()
                    self._log_cache_stats_if_needed(run_id=run_id, debug_meta=debug_meta)
                    return await self._finalize_with_latency(
                        conversation_id=conversation.id,
                        user_text=text,
                        response=cached_response,
                        token_usage=token_usage,
                        channel=channel,
                        run_id=run_id,
                        debug_meta=debug_meta,
                        spans=spans,
                        total_started=total_started,
                        detail_mode_triggered=detail_mode_enabled,
                    )

            component_enabled = bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False))
            component_shadow_mode = bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False))
            component_require = bool(getattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False))
            if component_enabled and not component_shadow_mode:
                component_started = time.perf_counter()
                try:
                    component_result = await self._run_component_pipeline(
                        request=req,
                        conversation_id=conversation.id,
                        run_id=run_id,
                    )
                    detail_mode_enabled = bool(component_result.detail_mode_triggered)
                    for span_key, span_value in dict(component_result.spans or {}).items():
                        self._add_latency_span(spans, str(span_key), float(span_value or 0.0))
                    self._add_latency_span(
                        spans,
                        "response_build_ms",
                        (time.perf_counter() - component_started) * 1000.0,
                    )
                    debug_meta.update(dict(component_result.debug or {}))
                    debug_meta["component_mode"] = "active"
                    debug_meta["component_plan"] = list(
                        dict(component_result.debug or {}).get("component_plan") or []
                    )
                    external_state["llm_count"] = int(component_result.llm_calls or 0)
                    external_state["by_name"] = dict(component_result.external_call_counts or {})
                    external_state["count"] = int(sum(external_state["by_name"].values()))
                    token_usage = llm_service.consume_token_usage()
                    return await _finalize_and_cache(
                        component_result.response,
                        token_usage if isinstance(token_usage, dict) else None,
                    )
                except Exception as exc:
                    debug_meta["component_mode"] = "error"
                    debug_meta["component_pipeline_error"] = str(exc)
                    recovery_conversation_id: Optional[int] = None
                    try:
                        recovery_conversation_id = int(getattr(conversation, "id", 0) or 0)
                    except Exception:
                        recovery_conversation_id = None
                    try:
                        if hasattr(self.db, "rollback"):
                            await self.db.rollback()
                            debug_meta["component_pipeline_rollback"] = True
                            try:
                                user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
                                conversation = await self.get_or_create_conversation(
                                    user,
                                    recovery_conversation_id or req.conversation_id,
                                )
                                debug_meta["component_pipeline_context_recovered"] = True
                            except Exception as recover_exc:
                                debug_meta["component_pipeline_context_recovered"] = False
                                debug_meta["component_pipeline_context_recover_error"] = str(recover_exc)
                    except Exception as rollback_exc:
                        debug_meta["component_pipeline_rollback"] = False
                        debug_meta["component_pipeline_rollback_error"] = str(rollback_exc)
                    if component_require:
                        self._add_latency_span(
                            spans,
                            "response_build_ms",
                            (time.perf_counter() - component_started) * 1000.0,
                        )
                        error_response = ChatResponse(
                            conversation_id=conversation.id,
                            reply_text="I could not process that request right now.",
                            carousel_msg="",
                            product_carousel=[],
                            follow_up_questions=[],
                            intent="fallback_general",
                            sources=[],
                            debug=debug_meta,
                            components=[
                                ChatComponent(
                                    type="error",
                                    data={"message": "I could not process that request right now."},
                                )
                            ],
                            meta=ChatResponseMeta(
                                query_summary=text,
                                latency_ms=0.0,
                                source="error",
                                llm_calls=0,
                                embedding_calls=0,
                            ),
                        )
                        token_usage = llm_service.consume_token_usage()
                        return await _finalize_and_cache(
                            error_response,
                            token_usage if isinstance(token_usage, dict) else None,
                        )
            elif component_enabled and component_shadow_mode:
                debug_meta["component_mode"] = "shadow"
                shadow_started = time.perf_counter()
                try:
                    shadow_result = await self._run_component_pipeline(
                        request=req,
                        conversation_id=conversation.id,
                        run_id=run_id,
                    )
                    debug_meta["component_shadow_component_plan"] = list(
                        dict(shadow_result.debug or {}).get("component_plan") or []
                    )
                    debug_meta["component_shadow_component_count"] = int(
                        len(list(shadow_result.response.components or []))
                    )
                    debug_meta["component_shadow_source"] = str(
                        dict(shadow_result.debug or {}).get("component_source") or ""
                    )
                except Exception as exc:
                    debug_meta["component_shadow_error"] = str(exc)
                    recovery_conversation_id: Optional[int] = None
                    try:
                        recovery_conversation_id = int(getattr(conversation, "id", 0) or 0)
                    except Exception:
                        recovery_conversation_id = None
                    try:
                        if hasattr(self.db, "rollback"):
                            await self.db.rollback()
                            debug_meta["component_shadow_rollback"] = True
                            try:
                                user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
                                conversation = await self.get_or_create_conversation(
                                    user,
                                    recovery_conversation_id or req.conversation_id,
                                )
                                debug_meta["component_shadow_context_recovered"] = True
                            except Exception as recover_exc:
                                debug_meta["component_shadow_context_recovered"] = False
                                debug_meta["component_shadow_context_recover_error"] = str(recover_exc)
                    except Exception as rollback_exc:
                        debug_meta["component_shadow_rollback"] = False
                        debug_meta["component_shadow_rollback_error"] = str(rollback_exc)
                finally:
                    self._add_latency_span(
                        spans,
                        "component_shadow_ms",
                        (time.perf_counter() - shadow_started) * 1000.0,
                    )

            # 3) Ultra-cheap SKU pre-check before NLU
            sku_precheck_started = time.perf_counter()
            sku_candidate, sku_cards = await self._cheap_sku_precheck(user_text=text, limit=3)
            self._add_latency_span(spans, "db_product_lookup_ms", (time.perf_counter() - sku_precheck_started) * 1000.0)
            if sku_cards:
                debug_meta["sku_precheck_hit"] = True
                debug_meta["sku_precheck_code"] = sku_candidate
                response_build_started = time.perf_counter()
                quick_reply = (
                    f"I found {len(sku_cards)} product(s) matching code {sku_candidate}. "
                    "Showing the latest item details."
                )
                response = await self._response_renderer.render(
                    conversation_id=conversation.id,
                    route="search_specific",
                    reply_data={"reply": quick_reply, "carousel_hint": "Matched products are shown below.", "recommended_questions": []},
                    product_carousel=list(sku_cards),
                    follow_up_questions=["Ask for price/stock/image for a specific SKU."],
                    sources=[],
                    debug=debug_meta,
                    reply_language=str(req.locale or "en-US"),
                    target_currency=str(heuristic_currency),
                    user_text=text,
                    apply_polish=False,
                )
                self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
            debug_meta["sku_precheck_hit"] = False

            # 4) Load history after hot cache + SKU pre-check
            history = []
            if conversation.id:
                history = await self.get_history(conversation.id, limit=8)
            max_history_tokens = max(64, int(getattr(settings, "CHAT_MAX_HISTORY_TOKENS", 1200)))
            history_for_llm = self._trim_history_for_llm(history, max_tokens=max_history_tokens)
            debug_meta["history_loaded_count"] = len(history)
            debug_meta["history_for_llm_count"] = len(history_for_llm)
            debug_meta["history_token_cap"] = max_history_tokens

            # 5) Heuristic-first NLU with threshold
            llm_parse_started = time.perf_counter()
            try:
                nlu_data = await self._run_nlu(
                    user_text=text,
                    history=history_for_llm,
                    locale=req.locale,
                    run_id=run_id,
                    external_state=external_state,
                    debug_meta=debug_meta,
                )
            except Exception:
                route_kind = "vague" if self._looks_vague_query(text) else "knowledge_query"
                response = await self._build_route_fallback_response(
                    conversation_id=conversation.id,
                    route_kind=route_kind,
                    reason=str(external_state.get("budget_exceeded_reason") or ExternalBudgetExceededReason.EXTERNAL_CONNECTIVITY.value),
                    user_text=text,
                    reply_language=str(req.locale or "en-US"),
                    target_currency=str(heuristic_currency),
                    debug_meta=debug_meta,
                )
                self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - llm_parse_started) * 1000.0)
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)

            self._add_latency_span(spans, "llm_parse_ms", (time.perf_counter() - llm_parse_started) * 1000.0)
            debug_meta["nlu"] = nlu_data

            reply_language = await self._resolve_reply_language(
                nlu_data=nlu_data,
                user_text=text,
                locale=req.locale,
                run_id=run_id,
            )
            debug_meta["reply_language"] = reply_language
            target_currency = await self._resolve_target_currency(nlu_data=nlu_data, user_text=text)
            debug_meta["target_currency"] = target_currency

            # 6) Intent routing + retrieval gate
            intent_started = time.perf_counter()
            intent_decision = IntentRouter.resolve(
                nlu_data=nlu_data,
                user_text=text,
                clean_code_candidate=self._clean_code_candidate,
                extract_sku=self._extract_sku,
                looks_like_code=self._looks_like_code,
            )
            self._add_latency_span(spans, "intent_routing_ms", (time.perf_counter() - intent_started) * 1000.0)
            search_query = intent_decision.search_query
            intent = intent_decision.intent
            show_products_flag = intent_decision.show_products_flag
            nlu_product_code = intent_decision.nlu_product_code
            sku_token = intent_decision.sku_token
    
            detail_parser_started = time.perf_counter()
            detail_request = DetailQueryParser.parse(user_text=text, nlu_data=nlu_data)
            self._add_latency_span(spans, "detail_query_parser_ms", (time.perf_counter() - detail_parser_started) * 1000.0)
    
            detail_mode_enabled = bool(getattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", True)) and bool(
                detail_request.is_detail_request
            )
            debug_meta["detail_mode_enabled"] = detail_mode_enabled
            debug_meta["requested_fields"] = list(detail_request.requested_fields)
            debug_meta["attribute_filters"] = dict(detail_request.attribute_filters)
            nlu_fields = [str(item).strip().lower() for item in list(nlu_data.get("requested_fields", []) or [])]
            if sorted(set(nlu_fields)) != sorted(set(detail_request.requested_fields)):
                logger.warning(
                    "detail parser adjusted requested_fields from nlu",
                    extra={
                        "event": "detail_parser_nlu_mismatch",
                        "nlu_fields": sorted(set(nlu_fields)),
                        "parser_fields": sorted(set(detail_request.requested_fields)),
                    },
                )
    
            gate_started = time.perf_counter()
            retrieval_decision = RetrievalGate.decide(
                intent=intent,
                show_products_flag=show_products_flag,
                is_product_intent=intent_decision.is_product_intent,
                sku_token=sku_token,
                strict_separation=bool(getattr(settings, "CHAT_STRICT_RETRIEVAL_SEPARATION_ENABLED", False)),
                has_attribute_filters=bool(detail_request.attribute_filters),
                detail_request=bool(detail_request.is_detail_request),
                user_text=text,
                infer_jewelry_type_filter=self._infer_jewelry_type_filter,
                is_question_like_fn=self._is_question_like,
                is_complex_query_fn=self._is_complex_query,
                count_policy_topics_fn=self._count_policy_topics,
            )
            self._add_latency_span(spans, "retrieval_gate_ms", (time.perf_counter() - gate_started) * 1000.0)
    
            use_products = retrieval_decision.use_products
            use_knowledge = retrieval_decision.use_knowledge
            is_question_like = retrieval_decision.is_question_like
            is_complex = retrieval_decision.is_complex
            policy_topic_count = retrieval_decision.policy_topic_count
            is_policy_intent = retrieval_decision.is_policy_intent
            looks_like_product = retrieval_decision.looks_like_product
            ctx = ChatContext(
                text=text,
                is_question_like=is_question_like,
                looks_like_product=looks_like_product,
                has_store_intent=use_products,
                is_policy_intent=is_policy_intent,
                policy_topic_count=policy_topic_count,
                sku_token=sku_token,
                requested_currency=target_currency if target_currency != default_display_currency.upper() else None,
            )
    
            debug_meta["intent"] = intent
            debug_meta["path_kind"] = (
                "product_only"
                if use_products and not use_knowledge
                else "knowledge_only"
                if use_knowledge and not use_products
                else "mixed"
                if use_products and use_knowledge
                else "none"
            )
            debug_meta["retrieval_gate"] = {
                "use_products": use_products,
                "use_knowledge": use_knowledge,
                "is_complex": is_complex,
                "is_policy_intent": is_policy_intent,
                "policy_topic_count": policy_topic_count,
            }
    
            # Optional agentic read-only tool path for live-state/tool-needed requests.
            agent_result = None
            agentic_enabled = self._is_agentic_channel_enabled(channel) and max(
                0, int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0))
            ) == 0
            agentic_suitable = AgentToolRegistry.is_tool_suitable(
                user_text=text,
                intent=intent,
                sku_token=sku_token,
            )
            if agentic_enabled and agentic_suitable:
                debug_meta["agentic"] = {
                    "attempted": True,
                    "eligible": True,
                    "channel": channel,
                }
                try:
                    orchestrator = AgentOrchestrator(
                        db=self.db,
                        run_id=run_id,
                        channel=channel,
                    )
                    agent_result = await orchestrator.run(
                        user_text=text,
                        history=history_for_llm,
                        reply_language=reply_language,
                    )
                except Exception as exc:
                    logger.error(f"Agentic orchestration failed: {exc}")
                    debug_meta["agentic_error"] = str(exc)
                    agent_result = None
    
                if agent_result and agent_result.final_reply and agent_result.used_tools:
                    debug_meta["agentic"] = {
                        "attempted": True,
                        "eligible": True,
                        "used_tools": True,
                        "tool_call_count": len(agent_result.trace),
                        "channel": channel,
                    }
                    agent_reply_data = await self._ensure_reply_consistency_with_products(
                        reply_data={
                            "reply": agent_result.final_reply,
                            "carousel_hint": agent_result.carousel_msg or "",
                            "recommended_questions": list(agent_result.follow_up_questions or []),
                        },
                        has_products=bool(agent_result.product_carousel),
                        reply_language=reply_language,
                        run_id=run_id,
                    )
                    response_build_started = time.perf_counter()
                    response = await self._response_renderer.render(
                        conversation_id=conversation.id,
                        route="agentic_tools",
                        reply_data=agent_reply_data,
                        product_carousel=list(agent_result.product_carousel or []),
                        follow_up_questions=list(agent_result.follow_up_questions or []),
                        sources=list(agent_result.sources or []),
                        debug=debug_meta,
                        reply_language=reply_language,
                        target_currency=target_currency,
                        user_text=text,
                        apply_polish=False,
                    )
                    self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
                    token_usage = llm_service.consume_token_usage() or {}
                    if isinstance(token_usage, dict):
                        token_usage["agent_tool_trace"] = list(agent_result.trace or [])
                        token_usage["agent_used_tools"] = True
                    return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
    
                fallback_enabled = bool(getattr(settings, "AGENTIC_ENABLE_FALLBACK", True))
                if not fallback_enabled:
                    debug_meta["agentic"] = {
                        "attempted": True,
                        "eligible": True,
                        "used_tools": bool(agent_result and agent_result.used_tools),
                        "fallback": False,
                        "channel": channel,
                    }
                    fallback_text = await self._localize_ui_text(
                        reply_language=reply_language,
                        text="I could not complete that request right now. Please try again.",
                        run_id=run_id,
                    )
                    response_build_started = time.perf_counter()
                    response = await self._response_renderer.render(
                        conversation_id=conversation.id,
                        route="agentic_tools",
                        reply_data={"reply": fallback_text, "carousel_hint": "", "recommended_questions": []},
                        product_carousel=[],
                        follow_up_questions=[],
                        sources=[],
                        debug=debug_meta,
                        reply_language=reply_language,
                        target_currency=target_currency,
                        user_text=text,
                        apply_polish=False,
                    )
                    self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
                    token_usage = llm_service.consume_token_usage()
                    return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
            else:
                debug_meta["agentic"] = {
                    "attempted": False,
                    "eligible": bool(agentic_suitable),
                    "enabled": bool(agentic_enabled),
                    "channel": channel,
                }

            # 7) SQL-first structured product retrieval
            query_embedding: Optional[List[float]] = None
            embedding_failed = False
            embedding_error: Optional[Exception] = None
            structured_results_found = False
            structured_meta: Dict[str, Any] = {}
            product_cards: List[ProductCard] = []
            best_distance: Optional[float] = None
            distance_by_id: Dict[str, float] = {}

            if (
                use_products
                and bool(getattr(settings, "CHAT_SQL_FIRST_ENABLED", True))
                and hasattr(self.db, "execute")
            ):
                structured_started = time.perf_counter()
                structured_result, structured_meta = await self._catalog_search.structured_search(
                    sku_token=sku_token or nlu_product_code,
                    attribute_filters=detail_request.attribute_filters,
                    limit=20 if detail_mode_enabled else 10,
                    candidate_cap=int(getattr(settings, "CHAT_STRUCTURED_CANDIDATE_CAP", 300)),
                    catalog_version=str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
                )
                self._add_latency_span(spans, "db_product_lookup_ms", (time.perf_counter() - structured_started) * 1000.0)
                product_cards = list(structured_result.cards or [])
                best_distance = structured_result.best_distance
                distance_by_id = dict(structured_result.distance_by_id or {})
                structured_results_found = bool(product_cards)
                debug_meta["structured_sql_hit"] = structured_results_found
                debug_meta["structured_query_cache_hit"] = bool(structured_meta.get("structured_query_cache_hit", False))
                debug_meta["structured_candidate_cap"] = int(structured_meta.get("structured_candidate_cap", 0))
                debug_meta["projection_hit"] = bool(structured_meta.get("projection_hit", False))
                debug_meta["projection_lookup_ms"] = float(structured_meta.get("projection_lookup_ms", 0.0) or 0.0)
                debug_meta["structured_read_mode"] = str(structured_meta.get("structured_read_mode", "eav"))
                self._add_latency_span(spans, "projection_lookup_ms", float(structured_meta.get("projection_lookup_ms", 0.0) or 0.0))
            else:
                debug_meta["structured_sql_hit"] = False
                debug_meta["structured_query_cache_hit"] = False
                debug_meta["projection_hit"] = False
                debug_meta["projection_lookup_ms"] = 0.0
                debug_meta["structured_read_mode"] = "disabled"

            # 8) Embedding gating + fail-fast external call wrapper
            should_embed = False
            embedding_skip_reason = EmbeddingSkippedReason.NOT_NEEDED
            if use_knowledge:
                should_embed = True
            elif use_products:
                if structured_results_found:
                    should_embed = False
                    embedding_skip_reason = EmbeddingSkippedReason.STRUCTURED_RESULTS_FOUND
                else:
                    should_embed = True

            if use_products and not use_knowledge and self._looks_vague_query(search_query):
                should_embed = True
                embedding_skip_reason = EmbeddingSkippedReason.NOT_NEEDED

            if not use_products and not use_knowledge:
                should_embed = False
                embedding_skip_reason = EmbeddingSkippedReason.DISABLED_BY_ROUTE

            if should_embed:
                embedding_started = time.perf_counter()
                try:
                    query_embedding = await self._run_external_call(
                        external_state=external_state,
                        call_name="embedding_query",
                        call_factory=lambda: llm_service.generate_embedding(search_query),
                        run_id=run_id,
                        debug_meta=debug_meta,
                    )
                except Exception as exc:
                    embedding_failed = True
                    embedding_error = exc
                    debug_meta["embedding_error"] = str(exc)
                    debug_meta["embedding_error_type"] = type(exc).__name__
                    self._log_event(
                        run_id=run_id,
                        location="chat_service.embedding.error",
                        data={
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "use_products": bool(use_products),
                            "use_knowledge": bool(use_knowledge),
                        },
                    )
                finally:
                    self._add_latency_span(spans, "vector_search_ms", (time.perf_counter() - embedding_started) * 1000.0)
            else:
                debug_meta["embedding_skipped_reason"] = str(embedding_skip_reason.value)

            if embedding_failed:
                if bool(getattr(settings, "CHAT_FAIL_FAST_ON_EMBEDDING_ERROR", True)):
                    debug_meta["embedding_fail_fast"] = True
                    response_build_started = time.perf_counter()
                    budget_reason = str(external_state.get("budget_exceeded_reason") or "").strip()
                    if budget_reason:
                        route_kind = "detail_mode" if detail_mode_enabled else (
                            "knowledge_query" if use_knowledge else "browse_products"
                        )
                        response = await self._build_route_fallback_response(
                            conversation_id=conversation.id,
                            route_kind=route_kind,
                            reason=budget_reason,
                            user_text=text,
                            reply_language=reply_language,
                            target_currency=target_currency,
                            debug_meta=debug_meta,
                            product_carousel=list(product_cards[:3]) if product_cards else [],
                        )
                    else:
                        response = await self._build_embedding_fail_fast_response(
                            conversation_id=conversation.id,
                            user_text=text,
                            reply_language=reply_language,
                            target_currency=target_currency,
                            debug_meta=debug_meta,
                            use_products=bool(use_products),
                            use_knowledge=bool(use_knowledge),
                        )
                    self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
                    token_usage = llm_service.consume_token_usage()
                    return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
                raise embedding_error or RuntimeError("Embedding generation failed")

            allow_detail_cache = bool(getattr(settings, "CHAT_DETAIL_ENABLE_SEMANTIC_CACHE", False))
            allow_semantic_cache = not detail_mode_enabled or allow_detail_cache
            debug_meta["semantic_cache_hit"] = False
            if query_embedding is not None and allow_semantic_cache:
                cache_hit = await semantic_cache_service.get_hit(
                    self.db,
                    query_embedding=query_embedding,
                    reply_language=reply_language,
                    target_currency=target_currency,
                )
                if cache_hit:
                    debug_meta["semantic_cache_hit"] = True
                    debug_meta["semantic_cache_distance"] = cache_hit.distance
                    cached = cache_hit.entry.response_json or {}
                    cached_products = [ProductCard(**p) for p in cached.get("product_carousel", [])]
                    cached_reply_text = str(cached.get("reply_text", ""))
                    cached_carousel_msg = str(cached.get("carousel_msg", ""))
                    cached_reply_text, cached_carousel_msg = await ResponseConsistencyPolicy.normalize_cached_response(
                        reply_text=cached_reply_text,
                        carousel_msg=cached_carousel_msg,
                        has_products=bool(cached_products),
                        localize_text=lambda text: self._localize_ui_text(
                            reply_language=reply_language,
                            text=text,
                            run_id=run_id,
                        ),
                    )
                    response = ChatResponse(
                        conversation_id=conversation.id,
                        reply_text=cached_reply_text,
                        carousel_msg=cached_carousel_msg,
                        product_carousel=cached_products,
                        follow_up_questions=list(cached.get("follow_up_questions", []) or []),
                        intent=str(cached.get("intent", "rag_strict")),
                        sources=[KnowledgeSource(**s) for s in cached.get("sources", [])],
                        debug=debug_meta,
                        view_button_text=str(cached.get("view_button_text", "View Product Details")),
                        material_label=str(cached.get("material_label", "Material")),
                        jewelry_type_label=str(cached.get("jewelry_type_label", "Jewelry Type")),
                    )
                    token_usage = llm_service.consume_token_usage()
                    return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
            elif query_embedding is not None:
                debug_meta["semantic_cache_skipped"] = "detail_mode"

            # Vector product fallback only when needed
            if (
                use_products
                and query_embedding is not None
                and not structured_results_found
                and hasattr(self.db, "execute")
            ):
                product_search_limit = max(1, int(getattr(settings, "CHAT_VECTOR_TOP_K", 12)))
                product_search_started = time.perf_counter()
                vector_cards, _distances, best_distance, distance_by_id = await self.smart_product_search(
                    query=search_query,
                    query_embedding=query_embedding,
                    limit=product_search_limit,
                    run_id=run_id,
                    extracted_code=nlu_product_code,
                )
                product_search_elapsed = (time.perf_counter() - product_search_started) * 1000.0
                prev_vector_ms = float(spans.get("vector_search_ms", 0.0) or 0.0)
                self._merge_catalog_metrics_into_spans(spans)
                if float(spans.get("vector_search_ms", 0.0) or 0.0) <= prev_vector_ms:
                    self._add_latency_span(spans, "vector_search_ms", product_search_elapsed)
                product_cards = list(vector_cards)
    
            if detail_mode_enabled:
                resolver = ProductDetailResolver()
                resolution = resolver.resolve_detail_request(
                    candidate_cards=product_cards,
                    distance_by_id=distance_by_id,
                    requested_fields=detail_request.requested_fields,
                    attribute_filters=detail_request.attribute_filters,
                    sku_token=sku_token,
                    nlu_product_code=nlu_product_code,
                    max_matches=int(getattr(settings, "CHAT_DETAIL_MAX_MATCHES", 3)),
                    min_confidence=float(getattr(settings, "CHAT_DETAIL_MIN_CONFIDENCE", 0.55)),
                )
                detail_builder = DetailResponseBuilder()
                detail_payload = detail_builder.build_detail_reply(
                    matches=resolution.matches,
                    requested_fields=resolution.requested_fields,
                    attribute_filters=resolution.attribute_filters,
                    missing_fields_by_product=resolution.missing_fields_by_product,
                    wants_image=detail_request.wants_image,
                    max_matches=int(getattr(settings, "CHAT_DETAIL_MAX_MATCHES", 3)),
                )
                debug_meta["detail_match_count"] = len(resolution.matches)
                debug_meta["detail_card_policy_reason"] = detail_payload.card_policy_reason
                debug_meta["detail_has_exact_match"] = resolution.has_exact_match
    
                response_build_started = time.perf_counter()
                response = await self._response_renderer.render(
                    conversation_id=conversation.id,
                    route="detail_mode",
                    reply_data={
                        "reply": detail_payload.reply_text,
                        "carousel_hint": detail_payload.carousel_msg,
                        "recommended_questions": list(detail_payload.follow_up_questions),
                    },
                    product_carousel=list(detail_payload.product_carousel),
                    follow_up_questions=list(detail_payload.follow_up_questions),
                    sources=[],
                    debug=debug_meta,
                    reply_language=reply_language,
                    target_currency=target_currency,
                    user_text=text,
                    apply_polish=False,
                )
                self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
    
            max_sub_questions = int(getattr(settings, "RAG_DECOMPOSE_MAX_SUBQUESTIONS", 5))
            kb_sources: List[KnowledgeSource] = []
            if use_knowledge and query_embedding is not None:
                kb_fetch_started = time.perf_counter()
                kb_sources, kb_debug = await self._knowledge_context.fetch_sources(
                    use_knowledge=use_knowledge,
                    search_query=search_query,
                    query_embedding=query_embedding,
                    ctx=ctx,
                    is_complex=is_complex,
                    is_question_like=is_question_like,
                    is_policy_intent=is_policy_intent,
                    policy_topic_count=policy_topic_count,
                    max_sub_questions=max_sub_questions,
                    run_id=run_id,
                )
                self._add_latency_span(spans, "vector_search_ms", (time.perf_counter() - kb_fetch_started) * 1000.0)
                debug_meta.update(kb_debug)
    
            sources: List[KnowledgeSource] = []
    
            # Override show_products_flag if we found an EXACT match (smart search)
            if best_distance is not None and best_distance == 0.0 and product_cards:
                logger.info("Forcing show_products=True due to exact SKU/MasterCode match")
                show_products_flag = True
                intent = "search_specific"
    
            top_products, product_sources, product_fallback_used = ProductContextAssembler.select_primary_products(
                product_cards=product_cards,
                best_distance=best_distance,
                show_products_flag=show_products_flag,
                intent=intent,
                default_threshold=float(getattr(settings, "PRODUCT_DISTANCE_THRESHOLD", 0.45)),
                allow_fallback_products=intent in {"browse_products", "search_specific"},
            )
            sources.extend(product_sources)
            if product_fallback_used:
                debug_meta["product_fallback_used"] = True
    
            # 4b. Cross-sell accessories (e.g., barbell attachments)
            cross_sell_products: List[ProductCard] = []
            cross_sell_label: Optional[str] = None
            cross_sell_used = False
            cross_sell_mode = str(getattr(settings, "CHAT_CROSS_SELL_MODE", "off") or "off").strip().lower()
            if top_products and cross_sell_mode == "inline":
                primary_type = self._infer_primary_jewelry_type(products=top_products, query_text=search_query)
                cross_sell_query = self._build_cross_sell_query(primary_type or "")
                cross_sell_label = self._build_cross_sell_label(primary_type or "")
                if cross_sell_query:
                    cross_embedding: Optional[List[float]] = None
                    cross_embed_started = time.perf_counter()
                    try:
                        cross_embedding = await self._run_external_call(
                            external_state=external_state,
                            call_name="embedding_cross_sell",
                            call_factory=lambda: llm_service.generate_embedding(cross_sell_query),
                            run_id=run_id,
                            debug_meta=debug_meta,
                        )
                    except Exception as exc:
                        debug_meta["cross_sell_embedding_error"] = str(exc)
                        self._log_event(
                            run_id=run_id,
                            location="chat_service.cross_sell.embedding_error",
                            data={"error_type": type(exc).__name__, "error": str(exc)},
                        )
                    finally:
                        self._add_latency_span(spans, "vector_search_ms", (time.perf_counter() - cross_embed_started) * 1000.0)

                    if cross_embedding is not None:
                        try:
                            cross_search_started = time.perf_counter()
                            cross_cards, _cross_distances, _cross_best, _cross_map = await self.search_products(
                                cross_embedding,
                                limit=int(getattr(settings, "CHAT_VECTOR_TOP_K", 12)),
                                run_id=run_id,
                            )
                            cross_search_elapsed = (time.perf_counter() - cross_search_started) * 1000.0
                            prev_vector_ms = float(spans.get("vector_search_ms", 0.0) or 0.0)
                            self._merge_catalog_metrics_into_spans(spans)
                            if float(spans.get("vector_search_ms", 0.0) or 0.0) <= prev_vector_ms:
                                self._add_latency_span(spans, "vector_search_ms", cross_search_elapsed)

                            exclude_ids = {str(p.id) for p in top_products}
                            cross_sell_products = self._filter_cross_sell_products(
                                products=cross_cards,
                                exclude_type=primary_type,
                                exclude_ids=exclude_ids,
                                limit=3,
                            )
                            if cross_sell_products:
                                remaining = max(0, 10 - len(top_products))
                                added = cross_sell_products[:remaining] if remaining else []
                                if added:
                                    top_products.extend(added)
                                    accessory_text = "\n".join(
                                        [
                                            f"TYPE: {p.attributes.get('jewelry_type', 'Accessory')}, NAME: {p.name}, SKU: {p.sku}, PRICE: {p.price} {p.currency}"
                                            for p in added
                                        ]
                                    )
                                    sources.append(
                                        KnowledgeSource(
                                            source_id="product_cross_sell",
                                            title="Compatible Accessories",
                                            content_snippet=f"Related accessories customers often pair with these items:\n{accessory_text}",
                                            relevance=0.35,
                                        )
                                    )
                                    debug_meta["cross_sell_used"] = True
                                    cross_sell_used = True
                        except Exception as exc:
                            debug_meta["cross_sell_search_error"] = str(exc)
                            self._log_event(
                                run_id=run_id,
                                location="chat_service.cross_sell.search_error",
                                data={"error_type": type(exc).__name__, "error": str(exc)},
                            )
            else:
                debug_meta["cross_sell_skipped"] = True
    
            sources.extend(kb_sources)
    
            max_answer_sources = int(getattr(settings, "RAG_MAX_SOURCES_IN_RESPONSE", 5))
            sources_for_answer = sources[:max_answer_sources]
            debug_meta["retrieved_source_count"] = len(sources)
            debug_meta["answer_source_count"] = len(sources_for_answer)

            # 4. Generate Response (Strict RAG)
            llm_answer_started = time.perf_counter()
            try:
                reply_data = await self._run_external_call(
                    external_state=external_state,
                    call_name="llm_answer",
                    call_factory=lambda: self.synthesize_answer(
                        question=text,
                        sources=sources_for_answer,
                        reply_language=reply_language,
                        history=history_for_llm,
                        run_id=run_id,
                    ),
                    run_id=run_id,
                    debug_meta=debug_meta,
                )
            except Exception:
                route_kind = "vague" if self._looks_vague_query(text) else (
                    "knowledge_query" if use_knowledge else "browse_products"
                )
                response = await self._build_route_fallback_response(
                    conversation_id=conversation.id,
                    route_kind=route_kind,
                    reason=str(external_state.get("budget_exceeded_reason") or ExternalBudgetExceededReason.EXTERNAL_CONNECTIVITY.value),
                    user_text=text,
                    reply_language=reply_language,
                    target_currency=target_currency,
                    debug_meta=debug_meta,
                    product_carousel=list(top_products[:3]) if top_products else [],
                )
                self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - llm_answer_started) * 1000.0)
                token_usage = llm_service.consume_token_usage()
                return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
            self._add_latency_span(spans, "llm_answer_ms", (time.perf_counter() - llm_answer_started) * 1000.0)

            if bool(getattr(settings, "CHAT_LLM_RENDER_ONLY_GUARD", True)):
                debug_meta["llm_render_only_guard"] = True
            reply_data = await self._ensure_reply_consistency_with_products(
                reply_data=reply_data,
                has_products=bool(top_products),
                reply_language=reply_language,
                run_id=run_id,
            )
            reply_data, sku_guard_triggered = self._enforce_llm_sku_guard(
                reply_data=reply_data,
                product_cards=top_products,
            )
            if sku_guard_triggered:
                debug_meta["llm_sku_guard_triggered"] = True
    
            # 5. Render
            # Add "See more" button if products are shown
            follow_up_questions = []
    
            # Priority 1: Context-aware questions from LLM
            if reply_data.get("recommended_questions"):
                follow_up_questions = reply_data["recommended_questions"]
    
            # Priority 2: Smart fallback IF no LLM suggestions and products exist
            elif top_products:
                # Extract the primary search term for "See more" query
                jewelry_type = top_products[0].attributes.get("jewelry_type", "")
                material = top_products[0].attributes.get("material", "")
                search_term = jewelry_type or material or "similar items"
                follow_up_questions = [f"See more {search_term}"]
    
            if cross_sell_used and cross_sell_label:
                accessory_question = f"Show {cross_sell_label}"
                if accessory_question not in follow_up_questions:
                    follow_up_questions.append(accessory_question)
    
            if top_products:
                out_of_stock_count = 0
                for product in top_products:
                    stock_value = str(product.stock_status or "").strip().lower()
                    if stock_value in {"out_of_stock", "stockstatus.out_of_stock"}:
                        out_of_stock_count += 1
                if out_of_stock_count * 2 >= len(top_products):
                    in_stock_question = "Show similar in-stock items"
                    if in_stock_question not in follow_up_questions:
                        follow_up_questions.append(in_stock_question)
    
            # Enforce limit of 5
            if len(follow_up_questions) > 5:
                follow_up_questions = follow_up_questions[:5]
    
            response_build_started = time.perf_counter()
            response = await self._response_renderer.render(
                conversation_id=conversation.id,
                route="rag_strict",
                reply_data=reply_data,
                product_carousel=top_products,
                follow_up_questions=follow_up_questions,
                sources=sources_for_answer,
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=text,
                apply_polish=False,
            )
            self._add_latency_span(spans, "response_build_ms", (time.perf_counter() - response_build_started) * 1000.0)
    
            if response.sources:
                payload = {
                    "reply_text": response.reply_text,
                    "carousel_msg": response.carousel_msg or "",
                    "product_carousel": [p.dict() for p in response.product_carousel],
                    "follow_up_questions": list(response.follow_up_questions or []),
                    "intent": response.intent,
                    "sources": [s.dict() for s in response.sources],
                    "view_button_text": response.view_button_text,
                    "material_label": response.material_label,
                    "jewelry_type_label": response.jewelry_type_label,
                }
                for p in payload["product_carousel"]:
                    if p.get("id"):
                        p["id"] = str(p["id"])
                await semantic_cache_service.save_hit(
                    self.db,
                    query_text=search_query,
                    query_embedding=query_embedding or [],
                    response_json=payload,
                    reply_language=reply_language,
                    target_currency=target_currency,
                )

            token_usage = llm_service.consume_token_usage()
            return await _finalize_and_cache(response, token_usage if isinstance(token_usage, dict) else None)
        except Exception as exc:
            token_usage = llm_service.consume_token_usage()
            _apply_external_debug()
            self._log_latency_error(
                run_id=run_id,
                debug_meta=debug_meta,
                spans=spans,
                total_started=total_started,
                detail_mode_triggered=detail_mode_enabled,
                token_usage=token_usage if isinstance(token_usage, dict) else None,
                error=exc,
            )
            raise
