from __future__ import annotations

import re
import logging
import time
from typing import Any, Dict, Sequence

from sqlalchemy import func, or_, select

from app.core.config import settings
from app.models.knowledge import KnowledgeArticle, KnowledgeChunk, KnowledgeChunkEnrichment, KnowledgeChunkTag
from app.schemas.chat import KnowledgeSource
from app.services.ai.llm_service import llm_service
from app.services.chat.routing import routing_policy
from app.services.chat.components.cache import stable_cache_key
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.chat.text_normalization import normalize_user_text
from app.services.knowledge.tagging import build_knowledge_query_tags

logger = logging.getLogger(__name__)

KNOWLEDGE_ANSWER_CACHE_VERSION = 2


class PipelineWorkflowKnowledgeMixin:
    _COMPANY_INFO_CATEGORY_BOOSTS = {
        "contact": 0.22,
        "about": 0.18,
        "company": 0.18,
        "store_overview": 0.18,
    }

    @classmethod
    def _fallback_subtype(
            cls,
            *,
            user_text: str,
            route_reason: str,
            attribute_filters: Dict[str, str],
            sku_tokens: Sequence[str],
        ) -> str:
            normalized = normalize_user_text(user_text)
            if not normalized:
                return "fallback_gibberish"
            if any(hint in normalized for hint in cls._FALLBACK_VALID_HINTS):
                return "fallback_uncertain"
            if re.search(r"(.)\1{4,}", normalized):
                return "fallback_gibberish"
            alpha_tokens = re.findall(r"[a-z]+", normalized)
            if not alpha_tokens:
                return "fallback_gibberish"
            if len(alpha_tokens) == 1:
                token = alpha_tokens[0]
                vowel_count = sum(1 for ch in token if ch in "aeiou")
                vowel_ratio = float(vowel_count) / max(1, len(token))
                if len(token) >= 8 and vowel_count <= 1:
                    return "fallback_gibberish"
                if len(token) >= 8 and vowel_ratio <= 0.30:
                    return "fallback_gibberish"
                if any(pattern in token for pattern in ("asdf", "qwer", "zxcv")):
                    return "fallback_gibberish"
                if len(token) >= 8 and len(set(token)) <= 3:
                    return "fallback_gibberish"
            return "fallback_uncertain"

    @classmethod
    def _company_info_search_profile(
            cls,
            *,
            text: str,
            preferred_query: str = "",
        ) -> Dict[str, Any]:
            clean_text = normalize_user_text(preferred_query or text)
            query_tags = build_knowledge_query_tags(clean_text)
            tag_set = {str(tag or "").strip().lower() for tag in list(query_tags or []) if str(tag or "").strip()}
            must_tags = []
            if "contact" in tag_set:
                must_tags = ["contact"]
            elif "store_overview" in tag_set:
                must_tags = ["store_overview"]
            boost_tags = list(dict.fromkeys(list(tag_set) + ["contact", "store_overview"]))
            if any(marker in clean_text for marker in ("address", "where", "location", "showroom", "visit", "hours", "open", "close")):
                query_text = "where is your company located"
                store_overview_request = True
            elif any(marker in clean_text for marker in ("contact", "sales", "support", "phone", "email", "whatsapp", "representative")):
                query_text = "how can I contact customer service"
                store_overview_request = False
            else:
                query_text = clean_text or "about your company"
                store_overview_request = True
            return {
                "query_text": query_text,
                "must_tags": must_tags,
                "boost_tags": boost_tags,
                "store_overview_request": store_overview_request,
            }

    @classmethod
    def _company_info_term_list(cls, text: str) -> list[str]:
            tokens = re.findall(r"[a-z0-9]+", normalize_user_text(text))
            deduped: list[str] = []
            seen: set[str] = set()
            for token in tokens:
                if len(token) < 3:
                    continue
                if token in seen:
                    continue
                seen.add(token)
                deduped.append(token)
                if len(deduped) >= 8:
                    break
            return deduped

    @classmethod
    def _build_company_info_sources_from_rows(
            cls,
            *,
            rows: Sequence[Any],
            terms: Sequence[str],
            limit: int,
        ) -> list[KnowledgeSource]:
            scored: list[tuple[float, KnowledgeSource]] = []
            for row in list(rows or []):
                chunk_id, title, category, url, summary_text, chunk_text = row
                haystack = normalize_user_text(" ".join(
                    part for part in (title, category, summary_text, chunk_text) if part
                ))
                term_hits = sum(1 for term in list(terms or []) if term and term in haystack)
                relevance = min(
                    0.99,
                    0.52
                    + min(0.28, 0.06 * float(term_hits))
                    + float(cls._COMPANY_INFO_CATEGORY_BOOSTS.get(normalize_user_text(category), 0.0)),
                )
                scored.append(
                    (
                        relevance,
                        KnowledgeSource(
                            source_id=str(chunk_id),
                            chunk_id=str(chunk_id),
                            title=str(title or ""),
                            summary=str(summary_text or "").strip() or None,
                            content_snippet=str(chunk_text or "")[: int(getattr(settings, "RAG_MAX_CHUNK_CHARS_FOR_CONTEXT", 600))],
                            category=str(category or ""),
                            relevance=relevance,
                            url=str(url or ""),
                            distance=max(0.0, 1.0 - relevance),
                        ),
                    )
                )
            scored.sort(key=lambda item: item[0], reverse=True)
            return [source for _score, source in scored[: max(1, int(limit))]]

    async def _search_company_info_lexical(
            self,
            *,
            query_text: str,
            must_tags: Sequence[str],
            boost_tags: Sequence[str],
            limit: int = 5,
        ) -> list[KnowledgeSource]:
            terms = self._company_info_term_list(query_text)
            if not terms and not list(must_tags or []) and not list(boost_tags or []):
                return []

            chunk_text_col = func.lower(func.coalesce(KnowledgeChunk.chunk_text, ""))
            title_col = func.lower(func.coalesce(KnowledgeArticle.title, ""))
            category_col = func.lower(func.coalesce(KnowledgeArticle.category, ""))
            summary_col = func.lower(func.coalesce(KnowledgeChunkEnrichment.summary_text, ""))

            text_filters = []
            for term in list(terms or []):
                like_term = f"%{term}%"
                text_filters.extend(
                    [
                        chunk_text_col.like(like_term),
                        title_col.like(like_term),
                        category_col.like(like_term),
                        summary_col.like(like_term),
                    ]
                )

            stmt = (
                select(
                    KnowledgeChunk.id,
                    KnowledgeArticle.title,
                    KnowledgeArticle.category,
                    KnowledgeArticle.url,
                    KnowledgeChunkEnrichment.summary_text,
                    KnowledgeChunk.chunk_text,
                )
                .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
                .outerjoin(KnowledgeChunkEnrichment, KnowledgeChunkEnrichment.chunk_id == KnowledgeChunk.id)
            )
            if list(must_tags or []) or list(boost_tags or []):
                stmt = stmt.outerjoin(KnowledgeChunkTag, KnowledgeChunkTag.chunk_id == KnowledgeChunk.id)
            stmt = stmt.where(
                or_(
                    KnowledgeArticle.active_version.is_(None),
                    KnowledgeChunk.version == KnowledgeArticle.active_version,
                )
            )
            if text_filters:
                stmt = stmt.where(or_(*text_filters))
            if list(must_tags or []):
                stmt = stmt.group_by(
                    KnowledgeChunk.id,
                    KnowledgeArticle.title,
                    KnowledgeArticle.category,
                    KnowledgeArticle.url,
                    KnowledgeChunkEnrichment.summary_text,
                    KnowledgeChunk.chunk_text,
                ).having(
                    func.count(func.distinct(KnowledgeChunkTag.tag)).filter(
                        KnowledgeChunkTag.tag.in_(list(must_tags or []))
                    ) >= len(set(list(must_tags or [])))
                )
            elif list(boost_tags or []):
                stmt = stmt.group_by(
                    KnowledgeChunk.id,
                    KnowledgeArticle.title,
                    KnowledgeArticle.category,
                    KnowledgeArticle.url,
                    KnowledgeChunkEnrichment.summary_text,
                    KnowledgeChunk.chunk_text,
                )
            stmt = stmt.limit(max(8, int(limit) * 3))
            rows = (await self.db.execute(stmt)).all()
            sources = self._build_company_info_sources_from_rows(
                rows=rows,
                terms=terms,
                limit=limit,
            )
            return sources

    async def _resolve_knowledge_payload(
            self,
            *,
            text: str,
            locale: str,
            run_id: str,
            store_overview_request: bool,
            normalized_text: str,
            preferred_query: str = "",
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> Dict[str, Any]:
            knowledge_error_message = ""
            knowledge_query = str(preferred_query or "").strip() or str(text or "").strip()
            knowledge_query_normalized = normalize_user_text(knowledge_query) or normalized_text
            knowledge_sources = []
            knowledge_answer = ""
            capabilities = build_chat_runtime_capabilities()
            high_risk_guard_enabled = bool(capabilities.chat_knowledge_high_risk_guard_enabled)
            knowledge_is_high_risk = high_risk_guard_enabled and self._is_high_risk_knowledge_request(text=knowledge_query)
            min_knowledge_relevance = float(capabilities.chat_knowledge_min_relevance)
            if int(capabilities.chat_hard_max_embeddings_per_request) > 0:
                try:
                    embed_started = time.perf_counter()
                    embedding = await llm_service.generate_embedding(knowledge_query)
                    spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                    external_call_counts["embedding_query"] = int(external_call_counts.get("embedding_query", 0)) + 1
                    knowledge_started = time.perf_counter()
                    knowledge_sources = await self._knowledge_retrieval.search(
                        query_text=knowledge_query,
                        query_embedding=embedding,
                        limit=5,
                        store_overview_request=store_overview_request,
                        run_id=run_id,
                    )
                    spans["vector_search_ms"] += (time.perf_counter() - knowledge_started) * 1000.0
                except Exception as exc:
                    debug_meta["component_knowledge_search_error"] = str(exc)
                    knowledge_error_message = self._KNOWLEDGE_UNAVAILABLE_MESSAGE

            top_knowledge_relevance = max(
                (float(getattr(source, "relevance", 0.0) or 0.0) for source in list(knowledge_sources or [])),
                default=0.0,
            )
            knowledge_sources_weak = self._knowledge_sources_are_weak(
                sources=knowledge_sources,
                min_relevance=min_knowledge_relevance,
            )
            debug_meta["knowledge_sources_weak"] = knowledge_sources_weak
            debug_meta["knowledge_is_high_risk"] = knowledge_is_high_risk
            debug_meta["knowledge_high_risk_guard_enabled"] = high_risk_guard_enabled
            debug_meta["knowledge_min_relevance"] = min_knowledge_relevance
            debug_meta["knowledge_top_relevance"] = top_knowledge_relevance
            debug_meta["knowledge_query_text"] = knowledge_query
            skip_knowledge_answer = bool(
                knowledge_is_high_risk and (bool(knowledge_error_message) or knowledge_sources_weak)
            )
            debug_meta["knowledge_answer_skipped"] = skip_knowledge_answer

            if not skip_knowledge_answer and not knowledge_error_message:
                llm_cache_key = stable_cache_key(
                    f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:knowledge_answer",
                    {
                        "cache_version": KNOWLEDGE_ANSWER_CACHE_VERSION,
                        "q": knowledge_query_normalized,
                        "locale": locale.lower(),
                        "source_ids": [source.source_id for source in knowledge_sources],
                        "store_overview_request": bool(store_overview_request),
                    },
                )
                try:
                    llm_started = time.perf_counter()
                    knowledge_answer, from_cache = await self._knowledge_answer_once(
                        question=knowledge_query,
                        sources=knowledge_sources,
                        locale=locale,
                        store_overview_request=store_overview_request,
                        llm_cache_key=llm_cache_key,
                        debug_meta=debug_meta,
                    )
                    spans["llm_answer_ms"] += (time.perf_counter() - llm_started) * 1000.0
                    if not from_cache:
                        external_call_counts["llm_answer"] = int(external_call_counts.get("llm_answer", 0)) + 1
                except Exception as exc:
                    debug_meta["component_knowledge_answer_error"] = str(exc)
                    knowledge_error_message = self._KNOWLEDGE_UNAVAILABLE_MESSAGE

            ambiguity_reason = ""
            if knowledge_error_message and knowledge_is_high_risk:
                ambiguity_reason = "knowledge_unavailable"
            elif knowledge_sources_weak and knowledge_is_high_risk:
                ambiguity_reason = "knowledge_needs_clarification"

            return {
                "knowledge_query": knowledge_query,
                "knowledge_sources": knowledge_sources,
                "knowledge_answer": knowledge_answer,
                "knowledge_error_message": knowledge_error_message,
                "knowledge_is_high_risk": knowledge_is_high_risk,
                "knowledge_sources_weak": knowledge_sources_weak,
                "min_knowledge_relevance": min_knowledge_relevance,
                "top_knowledge_relevance": top_knowledge_relevance,
                "skip_knowledge_answer": skip_knowledge_answer,
                "ambiguity_reason": ambiguity_reason,
            }

    async def _resolve_company_info_payload(
            self,
            *,
            text: str,
            locale: str,
            run_id: str,
            store_overview_request: bool,
            normalized_text: str,
            preferred_query: str = "",
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> Dict[str, Any]:
            profile = self._company_info_search_profile(
                text=text,
                preferred_query=preferred_query,
            )
            knowledge_query = str(profile["query_text"] or "").strip() or str(preferred_query or text or "").strip()
            lexical_started = time.perf_counter()
            knowledge_sources = await self._search_company_info_lexical(
                query_text=knowledge_query,
                must_tags=list(profile["must_tags"] or []),
                boost_tags=list(profile["boost_tags"] or []),
                limit=5,
            )
            spans["db_product_lookup_ms"] += (time.perf_counter() - lexical_started) * 1000.0
            lexical_confidence = max(
                (float(getattr(source, "relevance", 0.0) or 0.0) for source in list(knowledge_sources or [])),
                default=0.0,
            )
            debug_meta["company_info_lexical_used"] = True
            debug_meta["company_info_lexical_top_relevance"] = lexical_confidence
            debug_meta["company_info_must_tags"] = list(profile["must_tags"] or [])
            debug_meta["company_info_boost_tags"] = list(profile["boost_tags"] or [])
            debug_meta["knowledge_query_text"] = knowledge_query

            if lexical_confidence < 0.58 and int(build_chat_runtime_capabilities().chat_hard_max_embeddings_per_request) > 0:
                try:
                    embed_started = time.perf_counter()
                    embedding = await llm_service.generate_embedding(knowledge_query)
                    spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                    external_call_counts["embedding_query"] = int(external_call_counts.get("embedding_query", 0)) + 1
                    vector_started = time.perf_counter()
                    vector_sources = await self._knowledge_retrieval.search(
                        query_text=knowledge_query,
                        query_embedding=embedding,
                        limit=5,
                        must_tags=list(profile["must_tags"] or []),
                        boost_tags=list(profile["boost_tags"] or []),
                        store_overview_request=bool(store_overview_request or profile["store_overview_request"]),
                        run_id=run_id,
                    )
                    spans["vector_search_ms"] += (time.perf_counter() - vector_started) * 1000.0
                    if vector_sources:
                        knowledge_sources = vector_sources
                except Exception as exc:
                    debug_meta["component_company_info_vector_error"] = str(exc)

            top_knowledge_relevance = max(
                (float(getattr(source, "relevance", 0.0) or 0.0) for source in list(knowledge_sources or [])),
                default=0.0,
            )
            knowledge_sources_weak = self._knowledge_sources_are_weak(
                sources=knowledge_sources,
                min_relevance=float(build_chat_runtime_capabilities().chat_knowledge_min_relevance),
            )
            knowledge_answer = ""
            knowledge_error_message = ""
            if knowledge_sources:
                if bool(store_overview_request or profile["store_overview_request"]):
                    knowledge_answer = self._build_store_overview_knowledge_answer(sources=knowledge_sources)
                if not knowledge_answer:
                    llm_cache_key = stable_cache_key(
                        f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:company_info_answer",
                        {
                            "cache_version": KNOWLEDGE_ANSWER_CACHE_VERSION,
                            "q": normalize_user_text(knowledge_query) or normalized_text,
                            "locale": locale.lower(),
                            "source_ids": [source.source_id for source in knowledge_sources],
                            "store_overview_request": bool(store_overview_request or profile["store_overview_request"]),
                        },
                    )
                    llm_started = time.perf_counter()
                    knowledge_answer, from_cache = await self._knowledge_answer_once(
                        question=knowledge_query,
                        sources=knowledge_sources,
                        locale=locale,
                        store_overview_request=bool(store_overview_request or profile["store_overview_request"]),
                        llm_cache_key=llm_cache_key,
                        debug_meta=debug_meta,
                    )
                    spans["llm_answer_ms"] += (time.perf_counter() - llm_started) * 1000.0
                    if not from_cache:
                        external_call_counts["llm_answer"] = int(external_call_counts.get("llm_answer", 0)) + 1
            else:
                knowledge_error_message = self._KNOWLEDGE_UNAVAILABLE_MESSAGE

            ambiguity_reason = ""
            if not knowledge_sources:
                ambiguity_reason = "knowledge_needs_clarification"
            elif knowledge_sources_weak and not knowledge_answer:
                ambiguity_reason = "knowledge_needs_clarification"

            return {
                "knowledge_query": knowledge_query,
                "knowledge_sources": knowledge_sources,
                "knowledge_answer": knowledge_answer,
                "knowledge_error_message": knowledge_error_message,
                "knowledge_is_high_risk": False,
                "knowledge_sources_weak": knowledge_sources_weak,
                "min_knowledge_relevance": float(build_chat_runtime_capabilities().chat_knowledge_min_relevance),
                "top_knowledge_relevance": top_knowledge_relevance,
                "skip_knowledge_answer": False,
                "ambiguity_reason": ambiguity_reason,
            }

    async def _handle_company_info_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            run_id: str,
            store_overview_request: bool,
            normalized_text: str,
            preferred_query: str = "",
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> None:
            state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            payload = await self._resolve_company_info_payload(
                text=text,
                locale=locale,
                run_id=run_id,
                store_overview_request=store_overview_request,
                normalized_text=normalized_text,
                preferred_query=preferred_query,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            state.knowledge.sources = list(payload["knowledge_sources"] or [])
            state.knowledge.answer = str(payload["knowledge_answer"] or "")
            state.knowledge.error_message = str(payload["knowledge_error_message"] or "")
            state.retrieval.source = ComponentSource.KNOWLEDGE if state.knowledge.sources else ComponentSource.ERROR
            state.retrieval.result_count = len(state.knowledge.sources)
            if str(payload["ambiguity_reason"] or "").strip():
                state.decision.ambiguity_reason = str(payload["ambiguity_reason"] or "").strip()
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                debug_meta["component_company_info_needs_clarification"] = True

    async def _handle_knowledge_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            run_id: str,
            store_overview_request: bool,
            normalized_text: str,
            preferred_query: str = "",
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> None:
            state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            payload = await self._resolve_knowledge_payload(
                text=text,
                locale=locale,
                run_id=run_id,
                store_overview_request=store_overview_request,
                normalized_text=normalized_text,
                preferred_query=preferred_query,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            state.knowledge.sources = list(payload["knowledge_sources"] or [])
            state.knowledge.answer = str(payload["knowledge_answer"] or "")
            knowledge_error_message = str(payload["knowledge_error_message"] or "")
            knowledge_is_high_risk = bool(payload["knowledge_is_high_risk"])
            knowledge_sources_weak = bool(payload["knowledge_sources_weak"])
            min_knowledge_relevance = float(payload["min_knowledge_relevance"] or 0.0)
            top_knowledge_relevance = float(payload["top_knowledge_relevance"] or 0.0)

            if knowledge_error_message and knowledge_is_high_risk:
                state.decision.ambiguity_reason = "knowledge_unavailable"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.retrieval.source = ComponentSource.KNOWLEDGE
                state.retrieval.result_count = 0
                debug_meta["component_knowledge_fail_soft"] = True
                logger.debug("High-risk knowledge request downgraded to clarification because retrieval failed")
            elif knowledge_sources_weak and knowledge_is_high_risk:
                state.decision.ambiguity_reason = "knowledge_needs_clarification"
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                state.retrieval.source = ComponentSource.KNOWLEDGE
                state.retrieval.result_count = 0
                debug_meta["component_knowledge_needs_clarification"] = True
                logger.debug(
                    "High-risk knowledge request downgraded to clarification because top relevance %.2f is below %.2f",
                    top_knowledge_relevance,
                    min_knowledge_relevance,
                )
            elif knowledge_error_message:
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.ERROR]
                state.retrieval.source = ComponentSource.ERROR
                state.retrieval.result_count = 0
                debug_meta["component_knowledge_fail_soft"] = True
            else:
                state.retrieval.source = ComponentSource.KNOWLEDGE
                state.retrieval.result_count = len(state.knowledge.sources)
            state.knowledge.error_message = knowledge_error_message

    async def _handle_mixed_knowledge_enrichment(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            locale: str,
            run_id: str,
            store_overview_request: bool,
            normalized_text: str,
            preferred_query: str = "",
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> None:
            payload = await self._resolve_knowledge_payload(
                text=text,
                locale=locale,
                run_id=run_id,
                store_overview_request=store_overview_request,
                normalized_text=normalized_text,
                preferred_query=preferred_query,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            debug_meta["mixed_intent_knowledge_requested"] = True
            debug_meta["mixed_intent_knowledge_query"] = str(payload["knowledge_query"] or "")
            debug_meta["mixed_intent_knowledge_ambiguity_reason"] = str(payload["ambiguity_reason"] or "")

            if str(payload["ambiguity_reason"] or "").strip():
                debug_meta["mixed_intent_knowledge_used"] = False
                return
            if str(payload["knowledge_error_message"] or "").strip():
                debug_meta["mixed_intent_knowledge_used"] = False
                return
            if not str(payload["knowledge_answer"] or "").strip():
                debug_meta["mixed_intent_knowledge_used"] = False
                return

            state.knowledge.sources = list(payload["knowledge_sources"] or [])
            state.knowledge.answer = str(payload["knowledge_answer"] or "")
            if ComponentType.KNOWLEDGE_ANSWER not in state.presentation.selected_components:
                state.presentation.selected_components.append(ComponentType.KNOWLEDGE_ANSWER)
            debug_meta["mixed_intent_knowledge_used"] = True

    def _handle_fallback_workflow(
            self,
            *,
            state: PipelineWorkflowState,
            text: str,
            route_decision: routing_policy.WorkflowDecision,
            attribute_filters: Dict[str, Any],
            sku_tokens: Sequence[str],
        ) -> None:
            state.decision.ambiguity_reason = state.decision.ambiguity_reason or self._fallback_subtype(
                user_text=text,
                route_reason=str(route_decision.reason or ""),
                attribute_filters=dict(attribute_filters or {}),
                sku_tokens=list(sku_tokens or []),
            )
            state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
            state.retrieval.source = ComponentSource.ERROR
            state.retrieval.result_count = 0
