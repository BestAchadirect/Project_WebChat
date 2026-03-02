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
from app.services.chat import (
    deterministic_reply,
    follow_up_policy,
    nlu_runtime,
    persistence,
    process_chat_runtime,
    query_runtime,
    runtime_metrics,
    sku_precheck,
)
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
        return runtime_metrics.feature_flags_snapshot()
    @classmethod
    def _config_fingerprint(cls) -> Dict[str, Any]:
        snapshot = cls._feature_flags_snapshot()
        serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=True)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        return {"hash": digest, "flags": snapshot}

    @staticmethod
    def _estimated_tokens(value: str) -> int:
        return runtime_metrics.estimated_tokens(value)
    @classmethod
    def _trim_history_for_llm(cls, history: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
        return runtime_metrics.trim_history_for_llm(history=history, max_tokens=max_tokens)
    def _log_cache_stats_if_needed(self, *, run_id: str, debug_meta: Dict[str, Any]) -> None:
        interval = max(5, int(getattr(settings, "CHAT_CACHE_LOG_INTERVAL_SECONDS", 60)))
        now = time.time()
        if now - float(self.__class__._last_cache_stats_log_ts or 0.0) < interval:
            return
        self.__class__._last_cache_stats_log_ts = now
        structured_stats = self._catalog_search.structured_cache_stats()
        debug_meta["structured_query_cache_stats"] = structured_stats
        self._log_event(
            run_id=run_id,
            location="chat_service.cache.stats",
            data={
                "structured_query_cache": structured_stats,
            },
        )

    @staticmethod
    def _new_latency_spans() -> Dict[str, Any]:
        return runtime_metrics.new_latency_spans()
    @staticmethod
    def _add_latency_span(spans: Dict[str, Any], key: str, elapsed_ms: float) -> None:
        runtime_metrics.add_latency_span(spans, key, elapsed_ms)
    def _merge_catalog_metrics_into_spans(self, spans: Dict[str, Any]) -> None:
        runtime_metrics.merge_catalog_metrics_into_spans(spans=spans, catalog_search=self._catalog_search)
    def _build_latency_payload(
        self,
        *,
        spans: Dict[str, Any],
        total_started: float,
        detail_mode_triggered: bool,
        token_usage: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return runtime_metrics.build_latency_payload(
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_triggered,
            token_usage=token_usage,
        )
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
        return follow_up_policy.normalize_text(text)
    @classmethod
    def _keyword_tokens(cls, text: str) -> set[str]:
        return follow_up_policy.keyword_tokens(text=text, stopwords=cls._FOLLOW_UP_STOPWORDS)
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
        return follow_up_policy.is_follow_up_relevant(
            question=question,
            user_text=user_text,
            route=route,
            has_products=has_products,
            use_products=use_products,
            use_knowledge=use_knowledge,
            is_policy_intent=is_policy_intent,
            stopwords=cls._FOLLOW_UP_STOPWORDS,
            product_terms=cls._FOLLOW_UP_PRODUCT_TERMS,
            policy_terms=cls._FOLLOW_UP_POLICY_TERMS,
        )
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
        return follow_up_policy.filter_follow_up_questions(
            questions=questions,
            user_text=user_text,
            route=route,
            has_products=has_products,
            retrieval_gate=retrieval_gate,
            stopwords=cls._FOLLOW_UP_STOPWORDS,
            product_terms=cls._FOLLOW_UP_PRODUCT_TERMS,
            policy_terms=cls._FOLLOW_UP_POLICY_TERMS,
            limit=limit,
        )
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
        return deterministic_reply.embedding_failure_reply_text(use_products=use_products, use_knowledge=use_knowledge)
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
        return await deterministic_reply.build_embedding_fail_fast_response(
            service=self,
            conversation_id=conversation_id,
            user_text=user_text,
            reply_language=reply_language,
            target_currency=target_currency,
            debug_meta=debug_meta,
            use_products=use_products,
            use_knowledge=use_knowledge,
        )
    @staticmethod
    def _build_route_fallback_text(
        *,
        route_kind: str,
        reason: str,
    ) -> str:
        return deterministic_reply.build_route_fallback_text(route_kind=route_kind, reason=reason)
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
        return await deterministic_reply.build_route_fallback_response(
            service=self,
            conversation_id=conversation_id,
            route_kind=route_kind,
            reason=reason,
            user_text=user_text,
            reply_language=reply_language,
            target_currency=target_currency,
            debug_meta=debug_meta,
            product_carousel=product_carousel,
        )
    def _format_language_instruction(self, *, language: Optional[str], locale: Optional[str]) -> str:
        return nlu_runtime.format_language_instruction(language=language, locale=locale)
    def _heuristic_nlu_fast_path(self, *, user_text: str, locale: Optional[str]) -> tuple[Optional[Dict[str, Any]], float]:
        return nlu_runtime.heuristic_nlu_fast_path(service=self, user_text=user_text, locale=locale)
    @staticmethod
    def _looks_vague_query(text: str) -> bool:
        return nlu_runtime.looks_vague_query(text)
    @staticmethod
    def _is_connectivity_error(exc: Exception) -> bool:
        return nlu_runtime.is_connectivity_error(exc)
    @staticmethod
    def _is_llm_textual_call(call_name: str) -> bool:
        return nlu_runtime.is_llm_textual_call(call_name)
    async def _run_external_call(
        self,
        *,
        external_state: Dict[str, Any],
        call_name: str,
        call_factory,
        run_id: str,
        debug_meta: Dict[str, Any],
    ) -> Any:
        return await nlu_runtime.run_external_call(
            service=self,
            external_state=external_state,
            call_name=call_name,
            call_factory=call_factory,
            run_id=run_id,
            debug_meta=debug_meta,
        )
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
        return await nlu_runtime.run_nlu(
            service=self,
            user_text=user_text,
            history=history,
            locale=locale,
            run_id=run_id,
            external_state=external_state,
            debug_meta=debug_meta,
        )
    async def _resolve_reply_language(self, *, nlu_data: Dict[str, Any], user_text: str, locale: Optional[str], run_id: str) -> str:
        return await nlu_runtime.resolve_reply_language(
            nlu_data=nlu_data,
            user_text=user_text,
            locale=locale,
            run_id=run_id,
        )
    async def _resolve_target_currency(self, *, nlu_data: Dict[str, Any], user_text: str) -> str:
        return await nlu_runtime.resolve_target_currency(nlu_data=nlu_data, user_text=user_text)
    @staticmethod
    def _is_probable_sku_token(token: str) -> bool:
        return sku_precheck.is_probable_sku_token(token)
    def _extract_sku(self, text: str) -> Optional[str]:
        return sku_precheck.extract_sku(text)
    @staticmethod
    def _clean_code_candidate(token: str) -> str:
        return sku_precheck.clean_code_candidate(token)
    @classmethod
    def _looks_like_code(cls, token: str) -> bool:
        return sku_precheck.looks_like_code(token)
    @staticmethod
    def _parse_enabled_channels(raw: str) -> set[str]:
        return sku_precheck.parse_enabled_channels(raw)
    def _is_component_channel_allowed(self, *, channel: str) -> bool:
        return sku_precheck.is_component_channel_allowed(channel=channel)
    def _collect_sku_precheck_candidates(self, *, user_text: str) -> List[str]:
        return sku_precheck.collect_sku_precheck_candidates(user_text=user_text)
    @staticmethod
    def _sku_precheck_bypass_reason(*, user_text: str) -> str:
        return sku_precheck.sku_precheck_bypass_reason(user_text=user_text)
    def _should_run_sku_precheck(
        self,
        *,
        user_text: str,
        channel: str,
    ) -> tuple[bool, str, List[str]]:
        return sku_precheck.should_run_sku_precheck(user_text=user_text, channel=channel)
    async def _cheap_sku_precheck(
        self,
        *,
        user_text: str,
        limit: int = 3,
        candidates: Optional[List[str]] = None,
    ) -> tuple[Optional[str], List[ProductCard]]:
        return await sku_precheck.cheap_sku_precheck(
            user_text=user_text,
            search_by_exact_sku=self._search_products_by_exact_sku,
            limit=limit,
            candidates=candidates,
        )
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

    def _is_agentic_tool_suitable(
        self,
        *,
        user_text: str,
        intent: str,
        sku_token: Optional[str],
    ) -> bool:
        return AgentToolRegistry.is_tool_suitable(
            user_text=user_text,
            intent=intent,
            sku_token=sku_token,
        )

    def _new_agent_orchestrator(self, *, run_id: str, channel: str) -> AgentOrchestrator:
        return AgentOrchestrator(
            db=self.db,
            run_id=run_id,
            channel=channel,
        )

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
        return await persistence.save_message(
            db=self.db,
            conversation_id=conversation_id,
            role=role,
            content=content,
            product_data=product_data,
            token_usage=token_usage,
            commit=commit,
            touch_conversation=touch_conversation,
        )
    async def _finalize_response(
        self,
        *,
        conversation_id: int,
        user_text: str,
        response: ChatResponse,
        token_usage: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> ChatResponse:
        return await persistence.finalize_response(
            db=self.db,
            conversation_id=conversation_id,
            user_text=user_text,
            response=response,
            token_usage=token_usage,
            channel=channel,
        )
    async def submit_feedback(self, *, qa_log_id: UUID, feedback: int) -> Optional[QALog]:
        return await persistence.submit_feedback(db=self.db, qa_log_id=qa_log_id, feedback=feedback)
    async def get_history(self, conversation_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        return await persistence.get_history(db=self.db, conversation_id=conversation_id, limit=limit)
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
        return query_runtime.product_to_card(service=self, product=product, eav_attrs=eav_attrs)
    async def search_products(
        self,
        query_embedding: List[float],
        limit: int = 10,
        run_id: Optional[str] = None,
    ) -> Tuple[List[ProductCard], List[float], Optional[float], Dict[str, float]]:
        return await query_runtime.search_products(
            service=self,
            query_embedding=query_embedding,
            limit=limit,
            run_id=run_id,
        )
    async def synthesize_answer(
        self,
        question: str,
        sources: List[KnowledgeSource],
        reply_language: str,
        history: List[Dict[str, str]] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, str]:
        return await query_runtime.synthesize_answer(
            service=self,
            question=question,
            sources=sources,
            reply_language=reply_language,
            history=history,
            run_id=run_id,
        )
    @staticmethod
    def _build_product_list_filter_phrase(attribute_filters: Dict[str, str]) -> str:
        return deterministic_reply.build_product_list_filter_phrase(attribute_filters)
    @classmethod
    def _build_deterministic_product_reply_data(
        cls,
        *,
        products: List[ProductCard],
        attribute_filters: Dict[str, str],
    ) -> Dict[str, Any]:
        return deterministic_reply.build_deterministic_product_reply_data(
            products=products,
            attribute_filters=attribute_filters,
        )
    @staticmethod
    def _normalize_follow_up_attr_value(value: Any) -> str:
        return follow_up_policy.normalize_follow_up_attr_value(value)
    @classmethod
    def _has_product_context(
        cls,
        *,
        attribute_filters: Dict[str, str],
        user_text: str,
    ) -> bool:
        return follow_up_policy.has_product_context(
            attribute_filters=attribute_filters,
            user_text=user_text,
            stopwords=cls._FOLLOW_UP_STOPWORDS,
            product_terms=cls._FOLLOW_UP_PRODUCT_TERMS,
        )
    @classmethod
    def _extract_product_attribute_values(
        cls,
        *,
        products: List[ProductCard],
        key: str,
        limit: int = 3,
    ) -> List[str]:
        return follow_up_policy.extract_product_attribute_values(products=products, key=key, limit=limit)
    @classmethod
    def _build_product_follow_up_questions(
        cls,
        *,
        products: List[ProductCard],
        attribute_filters: Dict[str, str],
        user_text: str,
        limit: int = 4,
    ) -> List[str]:
        return follow_up_policy.build_product_follow_up_questions(
            products=products,
            attribute_filters=attribute_filters,
            user_text=user_text,
            stopwords=cls._FOLLOW_UP_STOPWORDS,
            product_terms=cls._FOLLOW_UP_PRODUCT_TERMS,
            limit=limit,
        )
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
        return await process_chat_runtime.process_chat(self, req, channel)
