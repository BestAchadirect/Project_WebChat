from __future__ import annotations

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
                    for source in (sources or [])[:5]
                ]
            )
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Answer strictly from provided context. "
                        "Prefer the enrichment summary when it is present; use the raw chunk excerpt only if the summary is missing or insufficient. "
                        "Use a natural, shopper-friendly tone that adapts to the user's phrasing. "
                        "Start with the direct answer. Do not use filler like 'Here is what I found'. "
                        "If multiple sources support the same answer, synthesize them into one short summary before replying. "
                        "Do not answer source-by-source or list snippets separately. "
                        "Rewrite FAQ bullets or headings into plain prose instead of copying them verbatim. "
                        "Keep the answer concise and practical, but preserve exact numbers, limits, dates, and conditions. "
                        "Do not invent products, SKUs, or policies not in context. "
                        "If the context is not enough, ask one short clarifying question instead of guessing. "
                        "Prefer one short paragraph over a bullet list unless the user explicitly asks for bullets. "
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
            answer = self._polish_knowledge_answer(
                answer=answer,
                question=question,
                max_sentences=4,
                max_chars=int(getattr(settings, "CHAT_KNOWLEDGE_ANSWER_MAX_CHARS", 420)),
            )
            if not answer:
                answer = self._build_grounded_knowledge_fallback_answer(
                    question=question,
                    sources=sources,
                )
            return answer, False
