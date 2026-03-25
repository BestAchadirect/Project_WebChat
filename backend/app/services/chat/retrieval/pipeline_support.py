from __future__ import annotations

from typing import Any, Dict, List

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
                value = normalize_user_text(str(raw_value or ""))
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

    async def _knowledge_answer_once(
            self,
            *,
            question: str,
            sources: List[KnowledgeSource],
            locale: str,
            store_overview_request: bool,
            llm_cache_key: str,
        ) -> tuple[str, bool]:
            cached = await self._redis_cache.get_json(llm_cache_key)
            if isinstance(cached, dict) and str(cached.get("answer", "")).strip():
                return str(cached.get("answer", "")), True
            if not list(sources or []):
                answer = self._build_grounded_knowledge_fallback_answer(
                    question=question,
                    sources=sources,
                )
                if answer:
                    await self._redis_cache.set_json(llm_cache_key, {"answer": answer}, ttl_seconds=120)
                return answer, False
            store_overview_answer = (
                self._build_store_overview_knowledge_answer(sources=sources) if store_overview_request else ""
            )
            if store_overview_answer:
                store_overview_answer = self._polish_knowledge_answer(
                    answer=store_overview_answer,
                    question=question,
                    max_sentences=3,
                    max_chars=int(getattr(settings, "CHAT_KNOWLEDGE_ANSWER_MAX_CHARS", 420)),
                )

            snippets = "\n".join(
                [
                    f"- {source.title}: {source.content_snippet}"
                    for source in (sources or [])[:5]
                ]
            )
            store_overview_prompt = ""
            if store_overview_request:
                store_overview_prompt = (
                    "If the question is about the company, showroom, location, or contact details, "
                    "prioritize those business details from the context before anything else. "
                )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "Answer strictly from provided context. "
                        "Use a professional and warm tone that adapts to the user's phrasing. "
                        "Start with a direct answer. Do not use filler like 'Here is what I found'. "
                        "Keep the answer concise and practical, usually 1-2 short sentences. "
                        "Do not invent products, SKUs, or policies not in context. "
                        "If the context is not enough, ask one short clarifying question instead of guessing. "
                        f"{store_overview_prompt}"
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
            answer = self._polish_knowledge_answer(
                answer=answer,
                question=question,
                max_sentences=4,
                max_chars=int(getattr(settings, "CHAT_KNOWLEDGE_ANSWER_MAX_CHARS", 420)),
            )
            if store_overview_request and store_overview_answer:
                normalized_answer = normalize_user_text(answer)
                looks_like_dump = normalized_answer.startswith("here is what i found")
                misses_store_signals = not any(
                    token in normalized_answer
                    for token in ("showroom", "address", "contact", "email", "phone", "bangkok")
                )
                if not answer or looks_like_dump or misses_store_signals:
                    answer = store_overview_answer
            if not answer:
                answer = store_overview_answer or self._build_grounded_knowledge_fallback_answer(
                    question=question,
                    sources=sources,
                )
            if answer:
                await self._redis_cache.set_json(llm_cache_key, {"answer": answer}, ttl_seconds=120)
            return answer, False
