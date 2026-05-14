from __future__ import annotations

from dataclasses import dataclass
import json
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
from app.services.chat.routing.signals import classify_fallback_reason
from app.services.chat.components.cache import stable_cache_key
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.runtime.capabilities import build_chat_runtime_capabilities
from app.services.chat.runtime.fallback_policy import knowledge_degrade_mode, knowledge_degrade_reason
from app.services.chat.runtime.grounding import evaluate_knowledge_grounding
from app.services.chat.text_normalization import normalize_user_text

logger = logging.getLogger(__name__)

KNOWLEDGE_ANSWER_CACHE_VERSION = 4


@dataclass(frozen=True)
class KnowledgeAnswerDependencyRule:
    key: str
    retrieval_scope: str
    retrieval_query: str
    query_markers: tuple[str, ...] = ()
    topic_markers: tuple[str, ...] = ()
    evidence_markers: tuple[str, ...] = ()
    title_category_markers: tuple[str, ...] = ()
    detail_markers: tuple[str, ...] = ()
    detail_patterns: tuple[str, ...] = ()
    must_tags: tuple[str, ...] = ()
    boost_tags: tuple[str, ...] = ()
    limit: int = 3
    debug_key: str = ""


class PipelineWorkflowKnowledgeMixin:
    _COMPANY_INFO_CATEGORY_BOOSTS = {
        "contact": 0.22,
        "about": 0.18,
        "company": 0.18,
        "store_overview": 0.18,
    }
    _COMPANY_INFO_PLAN_CACHE_VERSION = 1
    _COMPANY_INFO_SELECTOR_CACHE_VERSION = 1
    _KNOWLEDGE_ANSWER_DEPENDENCY_RULES = (
        KnowledgeAnswerDependencyRule(
            key="contact_details",
            debug_key="contact_dependency",
            retrieval_scope="company_info",
            retrieval_query="customer support contact email phone showroom sales",
            query_markers=(
                "refund",
                "return",
                "exchange",
                "replacement",
                "replace",
                "wrong item",
                "wrong product",
                "wrong order",
                "damaged",
                "defective",
                "rma",
            ),
            topic_markers=("refund", "refunds", "return", "returns", "support"),
            evidence_markers=(
                "contact us",
                "contact support",
                "customer service",
                "sales team",
                "support team",
                "email us",
                "call us",
                "phone",
                "email",
                "rma",
            ),
            title_category_markers=(
                "contact",
                "support",
                "customer service",
                "sales",
            ),
            detail_markers=("phone", "email", "whatsapp", "showroom"),
            detail_patterns=(
                r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
                r"(?<!\w)(?:\+\d[\d\s().-]{6,}\d|\d[\d\s().-]{7,}\d)(?!\w)",
            ),
            must_tags=("contact",),
            boost_tags=("contact", "support", "sales"),
        ),
        KnowledgeAnswerDependencyRule(
            key="showroom_details",
            debug_key="showroom_dependency",
            retrieval_scope="company_info",
            retrieval_query="showroom address location opening hours visit phone email bangkok",
            query_markers=(
                "showroom",
                "show room",
                "location",
                "address",
                "opening hours",
                "opening hour",
                "open",
                "hours",
                "visit",
                "where are you",
            ),
            topic_markers=("showroom", "location", "address", "hours", "store overview"),
            evidence_markers=("showroom", "visit", "location", "address", "open", "hours"),
            title_category_markers=("address", "location", "hours"),
            detail_markers=(
                "address",
                "open",
                "hours",
                "bangkok",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ),
            detail_patterns=(
                r"(?i)\b(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
                r"(?i)\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b",
            ),
            must_tags=("store_overview",),
            boost_tags=("showroom", "location", "address", "contact"),
        ),
    )

    @staticmethod
    def _apply_knowledge_ambiguity_state(
        *,
        state: PipelineWorkflowState,
        ambiguity_reason: str,
        debug_meta: Dict[str, Any],
        debug_prefix: str,
    ) -> None:
        state.decision.ambiguity_reason = ambiguity_reason
        state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
        if ambiguity_reason == "knowledge_unavailable":
            debug_meta[f"{debug_prefix}_fail_soft"] = True
        elif ambiguity_reason == "knowledge_needs_clarification":
            debug_meta[f"{debug_prefix}_needs_clarification"] = True

    @classmethod
    def _fallback_subtype(
            cls,
            *,
            user_text: str,
            route_reason: str,
            attribute_filters: Dict[str, str],
            sku_tokens: Sequence[str],
        ) -> str:
            del attribute_filters, sku_tokens
            return classify_fallback_reason(
                text=user_text,
                route_reason=route_reason,
                blank_reason="fallback_gibberish",
                default_reason="fallback_missing_signal",
                vague_hints=(
                    "help",
                    "assist",
                    "can you help",
                    "need help",
                    *tuple(cls._FALLBACK_VALID_HINTS or ()),
                ),
            )

    @staticmethod
    def _clean_llm_string_list(value: Any, *, limit: int = 8) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        seen: set[str] = set()
        for raw in value:
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(text)
            if len(items) >= max(1, int(limit)):
                break
        return items

    @staticmethod
    def _coerce_llm_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value or "").strip().lower() in {"true", "1", "yes"}

    @classmethod
    def _fallback_knowledge_plan(
            cls,
            *,
            text: str,
            preferred_query: str = "",
            store_overview_request: bool = False,
        ) -> Dict[str, Any]:
            query_text = str(preferred_query or text or "").strip()
            return {
                "query_text": query_text,
                "topic": "",
                "must_tags": [],
                "boost_tags": [],
                "required_evidence": [],
                "forbidden_topics": [],
                "store_overview_request": bool(store_overview_request),
                "answer_style": {
                    "max_sentences": 2,
                    "tone": "direct_customer_service",
                },
                "source": "fallback",
            }

    @classmethod
    def _normalize_knowledge_plan(
            cls,
            *,
            payload: Dict[str, Any],
            text: str,
            preferred_query: str = "",
            store_overview_request: bool = False,
        ) -> Dict[str, Any]:
            fallback = cls._fallback_knowledge_plan(
                text=text,
                preferred_query=preferred_query,
                store_overview_request=store_overview_request,
            )
            answer_style = payload.get("answer_style") if isinstance(payload.get("answer_style"), dict) else {}
            try:
                max_sentences = int(answer_style.get("max_sentences") or 2)
            except (TypeError, ValueError):
                max_sentences = 2
            max_sentences = min(3, max(1, max_sentences))
            query_text = str(
                payload.get("retrieval_query")
                or payload.get("query")
                or fallback.get("query_text")
                or preferred_query
                or text
                or ""
            ).strip()
            return {
                "query_text": query_text or str(fallback.get("query_text") or ""),
                "topic": str(payload.get("topic") or "").strip().lower(),
                "must_tags": cls._clean_llm_string_list(
                    payload.get("must_tags"),
                    limit=5,
                ),
                "boost_tags": cls._clean_llm_string_list(
                    payload.get("boost_tags"),
                    limit=8,
                ),
                "required_evidence": cls._clean_llm_string_list(payload.get("required_evidence"), limit=8),
                "forbidden_topics": cls._clean_llm_string_list(payload.get("forbidden_topics"), limit=8),
                "store_overview_request": cls._coerce_llm_bool(
                    payload.get("store_overview_request", fallback.get("store_overview_request"))
                ),
                "answer_style": {
                    "max_sentences": max_sentences,
                    "tone": str(answer_style.get("tone") or "direct_customer_service").strip(),
                },
                "source": "llm",
            }

    async def _plan_knowledge_retrieval(
            self,
            *,
            text: str,
            preferred_query: str,
            locale: str,
            store_overview_request: bool,
            debug_prefix: str,
            usage_kind: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> Dict[str, Any]:
            fallback = self._fallback_knowledge_plan(
                text=text,
                preferred_query=preferred_query,
                store_overview_request=store_overview_request,
            )
            model = str(
                getattr(settings, "CHAT_KNOWLEDGE_PLANNER_MODEL", "")
                or getattr(settings, "CHAT_COMPANY_KNOWLEDGE_PLANNER_MODEL", "")
                or getattr(settings, "CHAT_INTENT_CLASSIFICATION_MODEL", "")
                or getattr(settings, "NLU_MODEL", "gpt-5-mini")
            ).strip()
            if not model:
                debug_meta[f"{debug_prefix}_plan_source"] = "fallback_no_model"
                return dict(fallback)

            system_prompt = (
                "You plan retrieval for company/store knowledge-base questions across all FAQ topics. "
                "Return ONLY strict JSON with keys: retrieval_query, topic, must_tags, boost_tags, "
                "required_evidence, forbidden_topics, store_overview_request, answer_style. "
                "Use retrieval_query for database search, not final answering. "
                "Use must_tags only when evidence must come from one exact database topic; otherwise leave must_tags empty. "
                "Use boost_tags only as optional retrieval hints from source metadata. "
                "Handle contact, support, shipping, returns, refunds, payment, ordering, samples, showroom, "
                "custom manufacturing, marketing assets, website/currency, stock, product FAQ, trust/reference, "
                "language support, taxes, discounts, product care, and company/location questions. "
                "Do not force unrelated policy topics into the query. "
                "Do not invent company facts. Keep answer_style.max_sentences between 1 and 3."
            )
            payload = {
                "user_text": str(text or "").strip(),
                "preferred_query": str(preferred_query or "").strip(),
                "locale": str(locale or "en-US").strip() or "en-US",
            }
            try:
                started = time.perf_counter()
                data = await llm_service.generate_chat_json(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
                    ],
                    model=model,
                    temperature=0.0,
                    max_tokens=int(
                        getattr(
                            settings,
                            "CHAT_KNOWLEDGE_PLAN_MAX_TOKENS",
                            getattr(settings, "CHAT_COMPANY_KNOWLEDGE_PLAN_MAX_TOKENS", 500),
                        )
                    ),
                    reasoning_effort="minimal",
                    usage_kind=usage_kind,
                )
                spans["llm_answer_ms"] = float(spans.get("llm_answer_ms", 0.0)) + (
                    time.perf_counter() - started
                ) * 1000.0
                count_key = "llm_company_plan" if debug_prefix == "company_info" else "llm_knowledge_plan"
                external_call_counts[count_key] = int(external_call_counts.get(count_key, 0)) + 1
                plan = self._normalize_knowledge_plan(
                    payload=dict(data or {}),
                    text=text,
                    preferred_query=preferred_query,
                    store_overview_request=store_overview_request,
                )
                debug_meta[f"{debug_prefix}_plan_source"] = "llm"
                debug_meta[f"{debug_prefix}_plan"] = {
                    key: value
                    for key, value in plan.items()
                    if key in {"query_text", "topic", "must_tags", "boost_tags", "required_evidence", "forbidden_topics", "store_overview_request", "answer_style"}
                }
                return plan
            except Exception as exc:
                debug_meta[f"{debug_prefix}_plan_source"] = "fallback"
                debug_meta[f"{debug_prefix}_plan_error"] = str(exc)
                return dict(fallback)

    async def _plan_company_info_retrieval(
            self,
            *,
            text: str,
            preferred_query: str,
            locale: str,
            store_overview_request: bool,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> Dict[str, Any]:
            return await self._plan_knowledge_retrieval(
                text=text,
                preferred_query=preferred_query,
                locale=locale,
                store_overview_request=store_overview_request,
                debug_prefix="company_info",
                usage_kind="company_info_retrieval_plan",
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )

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

    @staticmethod
    def _company_candidate_payload(source: KnowledgeSource) -> Dict[str, Any]:
            return {
                "source_id": str(getattr(source, "source_id", "") or "").strip(),
                "chunk_id": str(getattr(source, "chunk_id", "") or "").strip(),
                "title": str(getattr(source, "title", "") or "").strip(),
                "category": str(getattr(source, "category", "") or "").strip(),
                "summary": str(getattr(source, "summary", "") or "").strip(),
                "snippet": str(getattr(source, "content_snippet", "") or "").strip()[:240],
                "relevance": float(getattr(source, "relevance", 0.0) or 0.0),
            }

    @staticmethod
    def _knowledge_selector_failed(
            *,
            debug_meta: Dict[str, Any],
            debug_prefix: str,
        ) -> bool:
            selector_source = str(debug_meta.get(f"{debug_prefix}_selector_source") or "").strip()
            return selector_source in {"unavailable", "unavailable_no_model"}

    @classmethod
    def _fallback_to_retrieved_knowledge_sources(
            cls,
            *,
            debug_meta: Dict[str, Any],
            debug_prefix: str,
            candidates: Sequence[KnowledgeSource],
            limit: int,
        ) -> list[KnowledgeSource]:
            selected = list(candidates or [])[: max(1, int(limit))]
            if not selected:
                return []
            reason = str(debug_meta.get(f"{debug_prefix}_selector_error") or "selector_unavailable").strip()
            debug_meta[f"{debug_prefix}_selector_fallback_used"] = True
            debug_meta[f"{debug_prefix}_selector_fallback_reason"] = reason
            debug_meta[f"{debug_prefix}_selector_fallback_source_ids"] = [
                str(getattr(source, "source_id", "") or getattr(source, "chunk_id", "") or "")
                for source in selected
            ]
            return selected

    async def _select_knowledge_sources_with_llm(
            self,
            *,
            knowledge_query: str,
            plan: Dict[str, Any],
            candidates: Sequence[KnowledgeSource],
            locale: str,
            debug_prefix: str,
            usage_kind: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
            limit: int = 3,
        ) -> list[KnowledgeSource]:
            candidate_list = list(candidates or [])
            if not candidate_list:
                debug_meta[f"{debug_prefix}_selector_source"] = "empty_candidates"
                return []

            model = str(
                getattr(settings, "CHAT_KNOWLEDGE_SELECTOR_MODEL", "")
                or getattr(settings, "CHAT_COMPANY_KNOWLEDGE_SELECTOR_MODEL", "")
                or getattr(settings, "CHAT_INTENT_CLASSIFICATION_MODEL", "")
                or getattr(settings, "NLU_MODEL", "gpt-5-mini")
            ).strip()
            if not model:
                debug_meta[f"{debug_prefix}_selector_source"] = "unavailable_no_model"
                return []

            candidates_payload = [self._company_candidate_payload(source) for source in candidate_list[:6]]
            system_prompt = (
                "You select evidence for a grounded company/store knowledge answer across any FAQ topic. "
                "Return ONLY compact strict JSON with keys: answerable, selected_source_ids, missing_evidence, reason. "
                "Select at most 3 chunks that directly answer the user's question. "
                "Reject unrelated or weak chunks even when broad words overlap. "
                "The chunk content is authoritative. If no chunk directly supports the answer, set answerable=false. "
                "Do not create facts."
            )
            payload = {
                "question": str(knowledge_query or "").strip(),
                "locale": str(locale or "en-US").strip() or "en-US",
                "plan": {
                    "topic": str(plan.get("topic") or ""),
                    "required_evidence": list(plan.get("required_evidence") or []),
                    "forbidden_topics": list(plan.get("forbidden_topics") or []),
                    "answer_style": dict(plan.get("answer_style") or {}),
                },
                "candidates": candidates_payload,
            }
            try:
                started = time.perf_counter()
                data = await llm_service.generate_chat_json(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
                    ],
                    model=model,
                    temperature=0.0,
                    max_tokens=int(
                        getattr(
                            settings,
                            "CHAT_KNOWLEDGE_SELECTOR_MAX_TOKENS",
                            getattr(settings, "CHAT_COMPANY_KNOWLEDGE_SELECTOR_MAX_TOKENS", 700),
                        )
                    ),
                    reasoning_effort="minimal",
                    timeout=float(
                        getattr(
                            settings,
                            "CHAT_KNOWLEDGE_SELECTOR_TIMEOUT_SECONDS",
                            getattr(settings, "CHAT_COMPANY_KNOWLEDGE_SELECTOR_TIMEOUT_SECONDS", 15.0),
                        )
                    ),
                    usage_kind=usage_kind,
                )
                spans["llm_answer_ms"] = float(spans.get("llm_answer_ms", 0.0)) + (
                    time.perf_counter() - started
                ) * 1000.0
                count_key = "llm_company_selector" if debug_prefix == "company_info" else "llm_knowledge_selector"
                external_call_counts[count_key] = int(external_call_counts.get(count_key, 0)) + 1
            except Exception as exc:
                debug_meta[f"{debug_prefix}_selector_source"] = "unavailable"
                debug_meta[f"{debug_prefix}_selector_error"] = str(exc)
                return []

            answerable = self._coerce_llm_bool((data or {}).get("answerable"))
            selected_ids = [
                str(item or "").strip()
                for item in self._clean_llm_string_list((data or {}).get("selected_source_ids"), limit=limit)
                if str(item or "").strip()
            ]
            by_source_id = {str(getattr(source, "source_id", "") or "").strip(): source for source in candidate_list}
            by_chunk_id = {str(getattr(source, "chunk_id", "") or "").strip(): source for source in candidate_list}
            selected: list[KnowledgeSource] = []
            for source_id in selected_ids:
                source = by_source_id.get(source_id) or by_chunk_id.get(source_id)
                if source is not None and source not in selected:
                    selected.append(source)
                if len(selected) >= max(1, int(limit)):
                    break

            debug_meta[f"{debug_prefix}_selector_source"] = "llm"
            debug_meta[f"{debug_prefix}_selector_answerable"] = bool(answerable)
            debug_meta[f"{debug_prefix}_selector_selected_ids"] = list(selected_ids)
            debug_meta[f"{debug_prefix}_selector_missing_evidence"] = self._clean_llm_string_list(
                (data or {}).get("missing_evidence"),
                limit=8,
            )
            debug_meta[f"{debug_prefix}_selector_reason"] = str((data or {}).get("reason") or "").strip()
            if not answerable:
                return []
            return selected

    async def _select_company_info_sources_with_llm(
            self,
            *,
            knowledge_query: str,
            plan: Dict[str, Any],
            candidates: Sequence[KnowledgeSource],
            locale: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
            limit: int = 3,
        ) -> list[KnowledgeSource]:
            return await self._select_knowledge_sources_with_llm(
                knowledge_query=knowledge_query,
                plan=plan,
                candidates=candidates,
                locale=locale,
                debug_prefix="company_info",
                usage_kind="company_info_evidence_select",
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
                limit=limit,
            )

    async def _retrieve_knowledge_sources(
            self,
            *,
            knowledge_query: str,
            store_overview_request: bool,
            run_id: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
            capabilities: Any,
        ) -> tuple[list[KnowledgeSource], str]:
            knowledge_sources: list[KnowledgeSource] = []
            knowledge_error_message = ""
            if int(capabilities.chat_hard_max_embeddings_per_request) <= 0:
                return knowledge_sources, knowledge_error_message
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
            return list(knowledge_sources or []), knowledge_error_message

    def _evaluate_knowledge_evidence(
            self,
            *,
            knowledge_sources: Sequence[KnowledgeSource],
            min_knowledge_relevance: float,
        ) -> tuple[float, bool]:
            top_knowledge_relevance = max(
                (float(getattr(source, "relevance", 0.0) or 0.0) for source in list(knowledge_sources or [])),
                default=0.0,
            )
            knowledge_sources_weak = self._knowledge_sources_are_weak(
                sources=knowledge_sources,
                min_relevance=min_knowledge_relevance,
            )
            return top_knowledge_relevance, knowledge_sources_weak

    @classmethod
    def _knowledge_source_text(cls, source: KnowledgeSource) -> str:
            return normalize_user_text(
                " ".join(
                    [
                        str(getattr(source, "title", "") or ""),
                        str(getattr(source, "category", "") or ""),
                        str(getattr(source, "summary", "") or ""),
                        str(getattr(source, "content_snippet", "") or ""),
                    ]
                )
            )

    @classmethod
    def _knowledge_dependency_debug_prefix(cls, rule: KnowledgeAnswerDependencyRule) -> str:
            debug_key = str(rule.debug_key or rule.key or "dependency").strip().lower()
            debug_key = re.sub(r"[^a-z0-9_]+", "_", debug_key).strip("_") or "dependency"
            return f"knowledge_{debug_key}"

    @staticmethod
    def _knowledge_source_dedupe_key(source: KnowledgeSource) -> str:
            source_id = str(getattr(source, "source_id", "") or getattr(source, "chunk_id", "") or "").strip()
            return source_id.lower() if source_id else str(id(source))

    @classmethod
    def _dedupe_knowledge_sources(
            cls,
            *,
            sources: Sequence[KnowledgeSource],
        ) -> list[KnowledgeSource]:
            deduped: list[KnowledgeSource] = []
            seen_ids: set[str] = set()
            for source in list(sources or []):
                dedupe_key = cls._knowledge_source_dedupe_key(source)
                if dedupe_key in seen_ids:
                    continue
                seen_ids.add(dedupe_key)
                deduped.append(source)
            return deduped

    @classmethod
    def _knowledge_source_satisfies_dependency(
            cls,
            *,
            source: KnowledgeSource,
            rule: KnowledgeAnswerDependencyRule,
        ) -> bool:
            title_category = normalize_user_text(
                " ".join(
                    [
                        str(getattr(source, "title", "") or ""),
                        str(getattr(source, "category", "") or ""),
                    ]
                )
            )
            detail_text_raw = " ".join(
                [
                    str(getattr(source, "summary", "") or ""),
                    str(getattr(source, "content_snippet", "") or ""),
                ]
            )
            detail_text = normalize_user_text(detail_text_raw)
            if not title_category and not detail_text:
                return False
            if any(marker in title_category for marker in tuple(rule.title_category_markers or ())):
                return True
            if any(marker in detail_text for marker in tuple(rule.detail_markers or ())):
                return True
            return any(re.search(pattern, detail_text_raw) for pattern in tuple(rule.detail_patterns or ()))

    @classmethod
    def _knowledge_requires_dependency(
            cls,
            *,
            rule: KnowledgeAnswerDependencyRule,
            user_text: str,
            topic: str,
            selected_sources: Sequence[KnowledgeSource],
        ) -> bool:
            normalized_user = normalize_user_text(user_text)
            topic_norm = normalize_user_text(topic)
            query_signal = any(marker in normalized_user for marker in tuple(rule.query_markers or ()))
            topic_signal = any(marker in topic_norm for marker in tuple(rule.topic_markers or ()))
            if not query_signal and not topic_signal:
                return False
            evidence_markers = tuple(rule.evidence_markers or ())
            if not evidence_markers:
                return True
            evidence_haystack = normalize_user_text(
                " ".join(cls._knowledge_source_text(source) for source in list(selected_sources or []))
            )
            if not evidence_haystack:
                return False
            return any(marker in evidence_haystack for marker in evidence_markers)

    @classmethod
    def _merge_knowledge_dependency_sources(
            cls,
            *,
            rule: KnowledgeAnswerDependencyRule,
            primary_sources: Sequence[KnowledgeSource],
            dependency_sources: Sequence[KnowledgeSource],
            limit: int = 3,
        ) -> tuple[list[KnowledgeSource], bool]:
            max_items = max(1, int(limit))
            deduped_primary = cls._dedupe_knowledge_sources(sources=primary_sources)
            if any(
                cls._knowledge_source_satisfies_dependency(source=source, rule=rule)
                for source in deduped_primary
            ):
                return deduped_primary[:max_items], False

            seen_ids = {cls._knowledge_source_dedupe_key(source) for source in deduped_primary}
            chosen_source: KnowledgeSource | None = None
            for source in list(dependency_sources or []):
                dedupe_key = cls._knowledge_source_dedupe_key(source)
                if dedupe_key in seen_ids:
                    continue
                if not cls._knowledge_source_satisfies_dependency(source=source, rule=rule):
                    continue
                chosen_source = source
                break
            if chosen_source is None:
                return deduped_primary[:max_items], False

            if max_items <= 1:
                return [chosen_source], True

            merged = list(deduped_primary[: max_items - 1])
            merged.append(chosen_source)
            for source in deduped_primary[max_items - 1:]:
                if len(merged) >= max_items:
                    break
                merged.append(source)
            return merged[:max_items], True

    async def _retrieve_knowledge_dependency_sources(
            self,
            *,
            rule: KnowledgeAnswerDependencyRule,
            locale: str,
            run_id: str,
            store_overview_request: bool,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> list[KnowledgeSource]:
            del locale
            if rule.retrieval_scope != "company_info":
                return []
            return await self._retrieve_company_info_sources(
                query_text=str(rule.retrieval_query or "").strip(),
                must_tags=list(rule.must_tags or []),
                boost_tags=list(rule.boost_tags or []),
                limit=max(1, int(rule.limit)),
                store_overview_request=store_overview_request,
                run_id=run_id,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )

    async def _enrich_knowledge_sources_with_dependencies(
            self,
            *,
            user_text: str,
            topic: str,
            selected_sources: Sequence[KnowledgeSource],
            locale: str,
            run_id: str,
            store_overview_request: bool,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> list[KnowledgeSource]:
            base_sources = self._dedupe_knowledge_sources(sources=selected_sources)
            required_rules: list[str] = []
            satisfied_rules: list[str] = []
            enriched_rules: list[str] = []
            rule_results: Dict[str, Dict[str, Any]] = {}

            for rule in self._KNOWLEDGE_ANSWER_DEPENDENCY_RULES:
                debug_prefix = self._knowledge_dependency_debug_prefix(rule)
                required = self._knowledge_requires_dependency(
                    rule=rule,
                    user_text=user_text,
                    topic=topic,
                    selected_sources=base_sources,
                )
                debug_meta[f"{debug_prefix}_required"] = bool(required)
                if not required:
                    continue
                required_rules.append(rule.key)

                if any(
                    self._knowledge_source_satisfies_dependency(source=source, rule=rule)
                    for source in base_sources
                ):
                    debug_meta[f"{debug_prefix}_satisfied"] = True
                    debug_meta[f"{debug_prefix}_enriched"] = False
                    satisfied_rules.append(rule.key)
                    rule_results[rule.key] = {"satisfied": True, "enriched": False}
                    continue

                retrieval_debug: Dict[str, Any] = {}
                try:
                    dependency_sources = await self._retrieve_knowledge_dependency_sources(
                        rule=rule,
                        locale=locale,
                        run_id=run_id,
                        store_overview_request=store_overview_request,
                        debug_meta=retrieval_debug,
                        spans=spans,
                        external_call_counts=external_call_counts,
                    )
                except Exception as exc:
                    debug_meta[f"{debug_prefix}_error"] = str(exc)
                    debug_meta[f"{debug_prefix}_satisfied"] = False
                    debug_meta[f"{debug_prefix}_enriched"] = False
                    rule_results[rule.key] = {
                        "satisfied": False,
                        "enriched": False,
                        "error": str(exc),
                    }
                    continue

                merged_sources, enriched = self._merge_knowledge_dependency_sources(
                    rule=rule,
                    primary_sources=base_sources,
                    dependency_sources=dependency_sources,
                    limit=max(1, int(rule.limit)),
                )
                base_sources = merged_sources
                satisfied = any(
                    self._knowledge_source_satisfies_dependency(source=source, rule=rule)
                    for source in merged_sources
                )
                debug_meta[f"{debug_prefix}_candidate_count"] = len(list(dependency_sources or []))
                debug_meta[f"{debug_prefix}_candidate_titles"] = [
                    str(getattr(source, "title", "") or "").strip()
                    for source in list(dependency_sources or [])
                    if str(getattr(source, "title", "") or "").strip()
                ][:3]
                debug_meta[f"{debug_prefix}_enriched"] = bool(enriched)
                debug_meta[f"{debug_prefix}_satisfied"] = bool(satisfied)
                if retrieval_debug:
                    debug_meta[f"{debug_prefix}_debug"] = {
                        key: value
                        for key, value in retrieval_debug.items()
                        if key.startswith("component_company_info_")
                    }
                if satisfied:
                    satisfied_rules.append(rule.key)
                if enriched:
                    enriched_rules.append(rule.key)
                rule_results[rule.key] = {
                    "satisfied": bool(satisfied),
                    "enriched": bool(enriched),
                    "candidate_count": len(list(dependency_sources or [])),
                }

            debug_meta["knowledge_dependency_rules_required"] = list(required_rules)
            debug_meta["knowledge_dependency_rules_satisfied"] = list(satisfied_rules)
            debug_meta["knowledge_dependency_rules_enriched"] = list(enriched_rules)
            if rule_results:
                debug_meta["knowledge_dependency_rule_results"] = dict(rule_results)
            return base_sources

    async def _attempt_grounded_knowledge_answer(
            self,
            *,
            knowledge_query: str,
            knowledge_query_normalized: str,
            knowledge_sources: Sequence[KnowledgeSource],
            locale: str,
            store_overview_request: bool,
            cache_prefix: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> tuple[str, str]:
            llm_cache_key = stable_cache_key(
                f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:{cache_prefix}",
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
                    sources=list(knowledge_sources or [])[:3],
                    locale=locale,
                    store_overview_request=store_overview_request,
                    llm_cache_key=llm_cache_key,
                    debug_meta=debug_meta,
                )
                spans["llm_answer_ms"] += (time.perf_counter() - llm_started) * 1000.0
                if not from_cache:
                    external_call_counts["llm_answer"] = int(external_call_counts.get("llm_answer", 0)) + 1
                return str(knowledge_answer or ""), ""
            except Exception as exc:
                debug_meta["component_knowledge_answer_error"] = str(exc)
                return "", self._KNOWLEDGE_UNAVAILABLE_MESSAGE

    async def _retrieve_company_info_sources(
            self,
            *,
            query_text: str,
            must_tags: Sequence[str],
            boost_tags: Sequence[str],
            limit: int,
            store_overview_request: bool,
            run_id: str,
            debug_meta: Dict[str, Any],
            spans: Dict[str, float],
            external_call_counts: Dict[str, int],
        ) -> list[KnowledgeSource]:
            lexical_started = time.perf_counter()
            effective_must_tags = list(must_tags or [])
            effective_boost_tags = list(boost_tags or [])
            knowledge_sources = await self._search_company_info_lexical(
                query_text=query_text,
                must_tags=effective_must_tags,
                boost_tags=effective_boost_tags,
                limit=limit,
            )
            spans["db_product_lookup_ms"] += (time.perf_counter() - lexical_started) * 1000.0
            if not knowledge_sources and effective_must_tags:
                broadened_started = time.perf_counter()
                effective_boost_tags = list(dict.fromkeys(effective_must_tags + effective_boost_tags))
                effective_must_tags = []
                knowledge_sources = await self._search_company_info_lexical(
                    query_text=query_text,
                    must_tags=effective_must_tags,
                    boost_tags=effective_boost_tags,
                    limit=limit,
                )
                spans["db_product_lookup_ms"] = float(spans.get("db_product_lookup_ms", 0.0)) + (
                    time.perf_counter() - broadened_started
                ) * 1000.0
                debug_meta["component_company_info_broadened_strict_tags"] = True
                debug_meta["component_company_info_effective_must_tags"] = list(effective_must_tags)
                debug_meta["component_company_info_effective_boost_tags"] = list(effective_boost_tags)
            lexical_confidence = max(
                (float(getattr(source, "relevance", 0.0) or 0.0) for source in list(knowledge_sources or [])),
                default=0.0,
            )
            if lexical_confidence >= 0.58 or int(build_chat_runtime_capabilities().chat_hard_max_embeddings_per_request) <= 0:
                return list(knowledge_sources or [])
            try:
                embed_started = time.perf_counter()
                embedding = await llm_service.generate_embedding(query_text)
                spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                external_call_counts["embedding_query"] = int(external_call_counts.get("embedding_query", 0)) + 1
                vector_started = time.perf_counter()
                vector_sources = await self._knowledge_retrieval.search(
                    query_text=query_text,
                    query_embedding=embedding,
                    limit=limit,
                    must_tags=list(effective_must_tags or []),
                    boost_tags=list(effective_boost_tags or []),
                    store_overview_request=store_overview_request,
                    run_id=run_id,
                )
                spans["vector_search_ms"] += (time.perf_counter() - vector_started) * 1000.0
                if vector_sources:
                    return list(vector_sources)
            except Exception as exc:
                debug_meta["component_company_info_vector_error"] = str(exc)
            return list(knowledge_sources or [])

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
            profile = await self._plan_knowledge_retrieval(
                text=text,
                preferred_query=preferred_query,
                locale=locale,
                store_overview_request=store_overview_request,
                debug_prefix="knowledge",
                usage_kind="knowledge_retrieval_plan",
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            knowledge_query = str(profile["query_text"] or "").strip() or str(preferred_query or text or "").strip()
            knowledge_query_normalized = normalize_user_text(knowledge_query) or normalized_text
            capabilities = build_chat_runtime_capabilities()
            high_risk_guard_enabled = bool(capabilities.chat_knowledge_high_risk_guard_enabled)
            knowledge_is_high_risk = high_risk_guard_enabled and self._is_high_risk_knowledge_request(text=knowledge_query)
            min_knowledge_relevance = float(capabilities.chat_knowledge_min_relevance)
            effective_store_overview_request = bool(store_overview_request or profile["store_overview_request"])
            knowledge_sources, knowledge_error_message = await self._retrieve_knowledge_sources(
                knowledge_query=knowledge_query,
                store_overview_request=effective_store_overview_request,
                run_id=run_id,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
                capabilities=capabilities,
            )
            top_knowledge_relevance, knowledge_sources_weak = self._evaluate_knowledge_evidence(
                knowledge_sources=knowledge_sources,
                min_knowledge_relevance=min_knowledge_relevance,
            )
            selected_sources = await self._select_knowledge_sources_with_llm(
                knowledge_query=knowledge_query,
                plan=profile,
                candidates=knowledge_sources,
                locale=locale,
                debug_prefix="knowledge",
                usage_kind="knowledge_evidence_select",
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
                limit=3,
            )
            if (
                not selected_sources
                and knowledge_sources
                and not knowledge_sources_weak
                and not knowledge_error_message
                and self._knowledge_selector_failed(debug_meta=debug_meta, debug_prefix="knowledge")
            ):
                selected_sources = self._fallback_to_retrieved_knowledge_sources(
                    debug_meta=debug_meta,
                    debug_prefix="knowledge",
                    candidates=knowledge_sources,
                    limit=3,
                )
            selected_sources = await self._enrich_knowledge_sources_with_dependencies(
                user_text=text,
                topic=str(profile.get("topic") or ""),
                selected_sources=selected_sources,
                locale=locale,
                run_id=run_id,
                store_overview_request=effective_store_overview_request,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            debug_meta["knowledge_source_count_before_selector"] = len(list(knowledge_sources or []))
            debug_meta["knowledge_source_count_after_selector"] = len(list(selected_sources or []))
            debug_meta["knowledge_sources_weak"] = knowledge_sources_weak
            debug_meta["knowledge_is_high_risk"] = knowledge_is_high_risk
            debug_meta["knowledge_high_risk_guard_enabled"] = high_risk_guard_enabled
            debug_meta["knowledge_min_relevance"] = min_knowledge_relevance
            debug_meta["knowledge_top_relevance"] = top_knowledge_relevance
            debug_meta["knowledge_query_text"] = knowledge_query
            skip_knowledge_answer = bool(
                not selected_sources
                or (knowledge_is_high_risk and (bool(knowledge_error_message) or knowledge_sources_weak))
            )
            debug_meta["knowledge_answer_skipped"] = skip_knowledge_answer
            knowledge_answer = ""
            if not skip_knowledge_answer and not knowledge_error_message:
                knowledge_answer, knowledge_error_message = await self._attempt_grounded_knowledge_answer(
                    knowledge_query=knowledge_query,
                    knowledge_query_normalized=knowledge_query_normalized,
                    knowledge_sources=selected_sources,
                    locale=locale,
                    store_overview_request=effective_store_overview_request,
                    cache_prefix="knowledge_answer",
                    debug_meta=debug_meta,
                    spans=spans,
                    external_call_counts=external_call_counts,
                )

            if not selected_sources and not knowledge_error_message:
                ambiguity_reason = "knowledge_needs_clarification"
            else:
                ambiguity_reason = knowledge_degrade_reason(
                    knowledge_error_message=knowledge_error_message,
                    knowledge_is_high_risk=knowledge_is_high_risk,
                    knowledge_sources_weak=knowledge_sources_weak,
                )

            return {
                "knowledge_query": knowledge_query,
                "knowledge_sources": selected_sources,
                "knowledge_answer": knowledge_answer,
                "knowledge_error_message": knowledge_error_message,
                "knowledge_is_high_risk": knowledge_is_high_risk,
                "knowledge_sources_weak": knowledge_sources_weak,
                "min_knowledge_relevance": min_knowledge_relevance,
                "top_knowledge_relevance": top_knowledge_relevance,
                "skip_knowledge_answer": skip_knowledge_answer,
                "ambiguity_reason": ambiguity_reason,
                "degrade_mode": knowledge_degrade_mode(degrade_reason=ambiguity_reason),
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
            profile = await self._plan_company_info_retrieval(
                text=text,
                preferred_query=preferred_query,
                locale=locale,
                store_overview_request=store_overview_request,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            knowledge_query = str(profile["query_text"] or "").strip() or str(preferred_query or text or "").strip()
            knowledge_sources = await self._retrieve_company_info_sources(
                query_text=knowledge_query,
                must_tags=list(profile["must_tags"] or []),
                boost_tags=list(profile["boost_tags"] or []),
                limit=12,
                store_overview_request=bool(store_overview_request or profile["store_overview_request"]),
                run_id=run_id,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
            )
            lexical_confidence = max(
                (float(getattr(source, "relevance", 0.0) or 0.0) for source in list(knowledge_sources or [])),
                default=0.0,
            )
            debug_meta["company_info_lexical_used"] = True
            debug_meta["company_info_lexical_top_relevance"] = lexical_confidence
            debug_meta["company_info_must_tags"] = list(profile["must_tags"] or [])
            debug_meta["company_info_boost_tags"] = list(profile["boost_tags"] or [])
            debug_meta["knowledge_query_text"] = knowledge_query
            min_knowledge_relevance = float(build_chat_runtime_capabilities().chat_knowledge_min_relevance)
            top_knowledge_relevance, knowledge_sources_weak = self._evaluate_knowledge_evidence(
                knowledge_sources=knowledge_sources,
                min_knowledge_relevance=min_knowledge_relevance,
            )
            focused_sources = await self._select_company_info_sources_with_llm(
                knowledge_query=knowledge_query,
                plan=profile,
                candidates=knowledge_sources,
                locale=locale,
                debug_meta=debug_meta,
                spans=spans,
                external_call_counts=external_call_counts,
                limit=3,
            )
            if (
                not focused_sources
                and knowledge_sources
                and not knowledge_sources_weak
                and self._knowledge_selector_failed(debug_meta=debug_meta, debug_prefix="company_info")
            ):
                focused_sources = self._fallback_to_retrieved_knowledge_sources(
                    debug_meta=debug_meta,
                    debug_prefix="company_info",
                    candidates=knowledge_sources,
                    limit=3,
                )
            debug_meta["company_info_plan_topic"] = str(profile.get("topic") or "")
            debug_meta["company_info_source_count_before_selector"] = len(list(knowledge_sources or []))
            debug_meta["company_info_source_count_after_selector"] = len(list(focused_sources or []))
            knowledge_answer = ""
            knowledge_error_message = ""
            if focused_sources:
                knowledge_answer, knowledge_error_message = await self._attempt_grounded_knowledge_answer(
                    knowledge_query=knowledge_query,
                    knowledge_query_normalized=normalize_user_text(knowledge_query) or normalized_text,
                    knowledge_sources=focused_sources,
                    locale=locale,
                    store_overview_request=bool(store_overview_request or profile["store_overview_request"]),
                    cache_prefix="company_info_answer",
                    debug_meta=debug_meta,
                    spans=spans,
                    external_call_counts=external_call_counts,
                )
            else:
                knowledge_error_message = self._KNOWLEDGE_UNAVAILABLE_MESSAGE

            ambiguity_reason = ""
            if not focused_sources:
                ambiguity_reason = "knowledge_needs_clarification"
            elif knowledge_error_message and not knowledge_answer:
                ambiguity_reason = "knowledge_unavailable"
            elif knowledge_sources_weak and not knowledge_answer:
                ambiguity_reason = "knowledge_needs_clarification"

            return {
                "knowledge_query": knowledge_query,
                "knowledge_sources": focused_sources,
                "knowledge_answer": knowledge_answer,
                "knowledge_error_message": knowledge_error_message,
                "knowledge_is_high_risk": False,
                "knowledge_sources_weak": knowledge_sources_weak,
                "min_knowledge_relevance": min_knowledge_relevance,
                "top_knowledge_relevance": top_knowledge_relevance,
                "skip_knowledge_answer": False,
                "ambiguity_reason": ambiguity_reason,
                "degrade_mode": knowledge_degrade_mode(degrade_reason=ambiguity_reason),
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
            grounding_decision = (
                evaluate_knowledge_grounding(
                    plan=state.decision.search_plan,
                    sources=state.knowledge.sources,
                    answer=state.knowledge.answer,
                    min_relevance=float(payload.get("min_knowledge_relevance", 0.0) or 0.0),
                    ambiguity_reason=str(payload["ambiguity_reason"] or ""),
                )
                if state.decision.search_plan is not None
                else None
            )
            if grounding_decision is not None:
                state.decision.knowledge_grounding_decision = grounding_decision
                debug_meta["knowledge_grounding"] = grounding_decision.to_debug_dict()
                debug_meta["knowledge_grounding_status"] = grounding_decision.status
                debug_meta["knowledge_grounding_safe_action"] = grounding_decision.safe_customer_action
                debug_meta["knowledge_grounding_reasons"] = list(grounding_decision.reasons)
            state.retrieval.source = ComponentSource.KNOWLEDGE if state.knowledge.sources else ComponentSource.ERROR
            state.retrieval.result_count = len(state.knowledge.sources)
            ambiguity_reason = str(payload["ambiguity_reason"] or "").strip()
            if not ambiguity_reason and grounding_decision is not None and grounding_decision.status != "grounded":
                ambiguity_reason = (
                    "knowledge_unavailable"
                    if grounding_decision.status == "unrelated"
                    else "knowledge_needs_clarification"
                )
            if ambiguity_reason:
                self._apply_knowledge_ambiguity_state(
                    state=state,
                    ambiguity_reason=ambiguity_reason,
                    debug_meta=debug_meta,
                    debug_prefix="component_company_info",
                )

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
            ambiguity_reason = str(payload["ambiguity_reason"] or "").strip()
            grounding_decision = (
                evaluate_knowledge_grounding(
                    plan=state.decision.search_plan,
                    sources=state.knowledge.sources,
                    answer=state.knowledge.answer,
                    min_relevance=float(payload.get("min_knowledge_relevance", 0.0) or 0.0),
                    ambiguity_reason=ambiguity_reason,
                )
                if state.decision.search_plan is not None
                else None
            )
            if grounding_decision is not None:
                state.decision.knowledge_grounding_decision = grounding_decision
                debug_meta["knowledge_grounding"] = grounding_decision.to_debug_dict()
                debug_meta["knowledge_grounding_status"] = grounding_decision.status
                debug_meta["knowledge_grounding_safe_action"] = grounding_decision.safe_customer_action
                debug_meta["knowledge_grounding_reasons"] = list(grounding_decision.reasons)
                if not ambiguity_reason and grounding_decision.status != "grounded":
                    ambiguity_reason = (
                        "knowledge_unavailable"
                        if grounding_decision.status == "unrelated"
                        else "knowledge_needs_clarification"
                    )

            if ambiguity_reason in {"knowledge_unavailable", "knowledge_needs_clarification"} and knowledge_is_high_risk:
                self._apply_knowledge_ambiguity_state(
                    state=state,
                    ambiguity_reason=ambiguity_reason,
                    debug_meta=debug_meta,
                    debug_prefix="component_knowledge",
                )
                state.retrieval.source = ComponentSource.KNOWLEDGE
                state.retrieval.result_count = 0
                if ambiguity_reason == "knowledge_unavailable":
                    logger.debug("High-risk knowledge request downgraded to clarification because retrieval failed")
            elif knowledge_error_message:
                state.presentation.selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.ERROR]
                state.retrieval.source = ComponentSource.ERROR
                state.retrieval.result_count = 0
                debug_meta["component_knowledge_fail_soft"] = True
            elif ambiguity_reason in {"knowledge_unavailable", "knowledge_needs_clarification"}:
                self._apply_knowledge_ambiguity_state(
                    state=state,
                    ambiguity_reason=ambiguity_reason,
                    debug_meta=debug_meta,
                    debug_prefix="component_knowledge",
                )
                state.retrieval.source = ComponentSource.KNOWLEDGE if state.knowledge.sources else ComponentSource.ERROR
                state.retrieval.result_count = 0
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
            grounding_decision = (
                evaluate_knowledge_grounding(
                    plan=state.decision.search_plan,
                    sources=list(payload["knowledge_sources"] or []),
                    answer=str(payload["knowledge_answer"] or ""),
                    min_relevance=float(payload.get("min_knowledge_relevance", 0.0) or 0.0),
                    ambiguity_reason=str(payload["ambiguity_reason"] or ""),
                )
                if state.decision.search_plan is not None
                else None
            )
            if grounding_decision is not None:
                state.decision.knowledge_grounding_decision = grounding_decision
                debug_meta["mixed_intent_knowledge_grounding"] = grounding_decision.to_debug_dict()
                debug_meta["mixed_intent_knowledge_grounding_status"] = grounding_decision.status

            if str(state.decision.ambiguity_reason or "").strip():
                debug_meta["mixed_intent_knowledge_used"] = False
                return
            if ComponentType.CLARIFY in state.presentation.selected_components or ComponentType.ERROR in state.presentation.selected_components:
                debug_meta["mixed_intent_knowledge_used"] = False
                return
            if str(payload["ambiguity_reason"] or "").strip():
                debug_meta["mixed_intent_knowledge_used"] = False
                return
            if grounding_decision is not None and grounding_decision.status != "grounded":
                debug_meta["mixed_intent_knowledge_used"] = False
                debug_meta["mixed_intent_knowledge_rejected_by_grounding"] = True
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
