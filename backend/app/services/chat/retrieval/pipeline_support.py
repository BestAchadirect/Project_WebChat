from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import case, select
from app.models.chat import Conversation, Message
from app.models.product import Product, StockStatus
from app.models.product_search_projection import ProductSearchProjection
from app.schemas.chat import KnowledgeSource
from app.services.ai.llm_service import llm_service
from app.core.config import settings
from app.services.chat.runtime import conversation_state
from app.services.chat.text_normalization import normalize_user_text


class PipelineSupportMixin:
    _ATTRIBUTE_LIST_BROADEN_KEYS = {
        "body_part",
        "color",
        "feature",
        "jewelry_type",
        "material",
        "presentation_type",
        "theme",
        "threading",
    }

    async def _load_store_overview_product_ids(self, *, limit: int = 40) -> List[str]:
            if not hasattr(self.db, "execute"):
                return []
            stmt = (
                select(Product.id)
                .where(Product.is_active.is_(True))
                .order_by(
                    case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                    Product.created_at.desc(),
                    Product.sku.asc(),
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
                "presentation_type": ProductSearchProjection.presentation_type_norm,
                "body_part": ProductSearchProjection.body_part_norm,
                "feature": ProductSearchProjection.feature_norm,
            }
            target_col = projection_cols.get(str(target or "").strip().lower())
            if target_col is None:
                return []

            def _base_stmt():
                return select(target_col).where(
                    ProductSearchProjection.is_active.is_(True),
                    target_col.is_not(None),
                    target_col != "",
                )

            def _apply_filters(*, broadening: bool) -> Any:
                stmt = _base_stmt()
                for raw_key, raw_value in dict(attribute_filters or {}).items():
                    key = str(raw_key or "").strip().lower()
                    if key == str(target or "").strip().lower():
                        continue
                    value = normalize_user_text(str(raw_value or ""))
                    if not value:
                        continue
                    filter_col = projection_cols.get(key)
                    if filter_col is None:
                        continue
                    if broadening and key in self._ATTRIBUTE_LIST_BROADEN_KEYS:
                        stmt = stmt.where(filter_col.ilike(f"%{value}%"))
                    else:
                        stmt = stmt.where(filter_col == value)
                return stmt.group_by(target_col).order_by(target_col.asc()).limit(max(1, int(limit)))

            stmt = _apply_filters(broadening=False)
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
            if values or not attribute_filters:
                return values

            broad_stmt = _apply_filters(broadening=True)
            try:
                broad_result = await self.db.execute(broad_stmt)
            except Exception:
                return values
            broad_values: List[str] = []
            broad_seen: set[str] = set()
            for raw in list(broad_result.scalars().all() or []):
                text = str(raw or "").strip()
                if not text:
                    continue
                key = text.lower()
                if key in broad_seen:
                    continue
                broad_seen.add(key)
                broad_values.append(self._display_attribute_value(text))
            return broad_values

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

    @staticmethod
    def _format_knowledge_source_context(source: KnowledgeSource) -> str:
        title = str(getattr(source, "title", "") or "").strip()
        summary = str(getattr(source, "summary", "") or "").strip()
        snippet = str(getattr(source, "content_snippet", "") or "").strip()
        if summary:
            if snippet and snippet != summary:
                return f"- {title} | enrichment summary: {summary} | raw excerpt: {snippet}"
            return f"- {title} | enrichment summary: {summary}"
        if snippet:
            return f"- {title} | raw excerpt: {snippet}"
        return f"- {title}"

    @staticmethod
    def _knowledge_fact_corpus(sources: List[KnowledgeSource]) -> str:
        parts: List[str] = []
        for source in list(sources or [])[:3]:
            parts.extend(
                [
                    str(getattr(source, "title", "") or ""),
                    str(getattr(source, "summary", "") or ""),
                    str(getattr(source, "content_snippet", "") or ""),
                    str(getattr(source, "url", "") or ""),
                ]
            )
        return " ".join(part for part in parts if part).lower()

    @staticmethod
    def _normalize_fact_phrase(value: str) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[\u2010-\u2015-]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip(" .,;:()[]{}")

    @classmethod
    def _unsupported_knowledge_facts(
            cls,
            *,
            answer: str,
            sources: List[KnowledgeSource],
        ) -> List[str]:
            answer_text = str(answer or "")
            if not answer_text.strip():
                return []

            source_text = cls._knowledge_fact_corpus(sources)
            source_text_normalized = cls._normalize_fact_phrase(source_text)
            source_digits = re.sub(r"\D+", "", source_text)
            unsupported: List[str] = []

            def _add_fact(kind: str, value: str) -> None:
                clean = str(value or "").strip().strip(".,;:)]}")
                if not clean:
                    return
                item = f"{kind}:{clean}"
                if item not in unsupported:
                    unsupported.append(item)

            for email in re.findall(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", answer_text):
                if email.lower() not in source_text:
                    _add_fact("email", email)

            for url in re.findall(r"(?i)\bhttps?://[^\s),;]+", answer_text):
                if url.lower().rstrip("/") not in source_text:
                    _add_fact("url", url)

            phone_candidates = re.findall(
                r"(?<!\w)(?:\+\d[\d\s().-]{6,}\d|\d[\d\s().-]{7,}\d)(?!\w)",
                answer_text,
            )
            for phone in phone_candidates:
                digits = re.sub(r"\D+", "", phone)
                if len(digits) >= 7 and digits not in source_digits:
                    _add_fact("phone", phone)

            quantified_pattern = re.compile(
                r"(?i)(?:\b(?:usd|eur|gbp|thb|baht)\s*\d[\d,]*(?:\.\d+)?\b|"
                r"\$\s*\d[\d,]*(?:\.\d+)?\b|"
                r"\b\d[\d,]*(?:\.\d+)?\s*(?:business\s+days?|days?|hours?|hrs?|months?|years?|baht|usd|thb|%|percent)\b)"
            )
            for match in quantified_pattern.findall(answer_text):
                phrase = cls._normalize_fact_phrase(match)
                if phrase and phrase not in source_text_normalized:
                    _add_fact("quantity", match)

            return unsupported

    @staticmethod
    def _summarize_knowledge_reply(answer: str) -> str:
        text = re.sub(r"(?m)^\s*(?:[•\-\*]|\d+\.)\s*", "", str(answer or ""))
        text = " ".join(text.split())
        if not text:
            return ""

        text = re.sub(r"^\s*here is what i found:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub("^\\s*(?:yes|no)\\b[\\s,;:\\u2014\\u2013-]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*[^A-Za-z0-9]+", "", text)

        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        summary = " ".join(sentences[:2]).strip() if sentences else text[:280].strip()
        if len(summary) > 320:
            trimmed = summary[:320]
            if " " in trimmed:
                trimmed = trimmed.rsplit(" ", 1)[0]
            summary = trimmed.rstrip(" ,;:") + "."
        return f"{summary}." if summary else ""

    @staticmethod
    def _polish_knowledge_answer(
            *,
            answer: str,
            question: str = "",
            max_sentences: int = 2,
            max_chars: int = 320,
        ) -> str:
            del question
            text = re.sub(r"(?m)^\s*(?:[\-\*]|\d+\.)\s*", "", str(answer or ""))
            text = " ".join(text.split()).strip()
            if not text:
                return ""
            text = re.sub(r"^\s*[^A-Za-z0-9]+", "", text)
            text = re.sub(r"^\s*[A-Za-z][A-Za-z\s]{1,40}:\s+", "", text)
            sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
            polished = " ".join(sentences[: max(1, int(max_sentences))]).strip() if sentences else text
            if len(polished) > max(1, int(max_chars)):
                trimmed = polished[: max(1, int(max_chars))]
                if " " in trimmed:
                    trimmed = trimmed.rsplit(" ", 1)[0]
                polished = trimmed.rstrip(" ,;:")
            polished = polished.rstrip(".!?")
            return f"{polished}." if polished else ""

    async def _knowledge_answer_once(
            self,
            *,
            question: str,
            sources: List[KnowledgeSource],
            locale: str,
            store_overview_request: bool,
            llm_cache_key: str,
            debug_meta: Optional[Dict[str, Any]] = None,
        ) -> tuple[str, bool]:
            if not list(sources or []):
                answer = self._build_grounded_knowledge_fallback_answer(
                    question=question,
                    sources=sources,
                )
                return answer, False

            snippets = "\n".join(
                [
                    self._format_knowledge_source_context(source)
                    for source in (sources or [])[:3]
                ]
            )
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Answer strictly from provided context. "
                        "Use the smallest set of sources that directly answer the user's question. "
                        "Do not mix unrelated policy, contact, or showroom details into the answer. "
                        "Prefer the enrichment summary when it is present; use the raw chunk excerpt only if the summary is missing or insufficient. "
                        "Use a natural, shopper-friendly tone that adapts to the user's phrasing. "
                        "Never use em dashes or en dashes; use commas, periods, parentheses, or ASCII hyphens instead. "
                        "Start with the direct answer. Do not use filler like 'Here is what I found'. "
                        "If multiple sources support the same answer, synthesize them into one short summary before replying. "
                        "Do not answer source-by-source or list snippets separately. "
                        "Rewrite FAQ bullets or headings into customer-friendly wording instead of copying them verbatim. "
                        "Keep the answer concise and practical, but preserve exact numbers, limits, dates, and conditions. "
                        "Do not invent products, SKUs, or policies not in context. "
                        "If the context is not enough, ask one short clarifying question instead of guessing. "
                        "For one-topic answers, use one short paragraph. "
                        "For multi-topic questions or answers that combine two or more distinct policy areas, use compact Markdown with bold section headings and 1-3 bullets per section. "
                        "Use section labels from the user's requested topics. If evidence is missing for one requested topic, include a short section for that topic that says the available context does not confirm it. "
                        "Do not return a long single paragraph for multi-topic answers. "
                        "Keep Markdown simple: bold headings and bullets only unless the user asks for another format. "
                        "Return JSON with a single key `reply`."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Locale: {locale}\n"
                        f"Question: {question}\n"
                        f"Source count: {len(list(sources or []))}\n"
                        f"Context:\n{snippets}\n\n"
                        "Respond in JSON. The reply value may contain Markdown."
                    ),
                },
            ]
            try:
                data = await llm_service.generate_chat_json(
                    messages,
                    model=getattr(settings, "RAG_ANSWER_MODEL", None) or settings.OPENAI_MODEL,
                    temperature=0.2,
                    max_tokens=int(getattr(settings, "CHAT_KNOWLEDGE_ANSWER_JSON_MAX_TOKENS", 700)),
                    reasoning_effort="minimal",
                    usage_kind="component_knowledge_answer",
                )
            except Exception as exc:
                if debug_meta is not None:
                    debug_meta["component_knowledge_answer_fallback_reason"] = str(exc)
                answer = self._build_grounded_knowledge_fallback_answer(
                    question=question,
                    sources=sources,
                )
                return answer, False
            answer = str(data.get("reply", "") or "").strip()
            unsupported_facts = self._unsupported_knowledge_facts(
                answer=answer,
                sources=sources,
            )
            if unsupported_facts:
                if debug_meta is not None:
                    debug_meta["component_knowledge_answer_rejected"] = True
                    debug_meta["component_knowledge_answer_rejection_reason"] = "unsupported_factual_claim"
                    debug_meta["component_knowledge_answer_unsupported_facts"] = list(unsupported_facts)
                answer = self._build_grounded_knowledge_fallback_answer(
                    question=question,
                    sources=sources,
                )
            if not answer:
                answer = self._build_grounded_knowledge_fallback_answer(
                    question=question,
                    sources=sources,
                )
            return answer, False
