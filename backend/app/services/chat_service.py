from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.config import settings
from app.models.chat import AppUser, Conversation, Message, MessageRole
from app.models.knowledge import KnowledgeArticle, KnowledgeChunk, KnowledgeChunkTag, KnowledgeEmbedding
from app.models.product import Product, ProductEmbedding
from app.schemas.chat import ChatRequest, ChatResponse, KnowledgeSource, ProductCard
from app.services.llm_service import llm_service
from app.services.rerank_service import rerank_service
from app.services.currency_service import currency_service
from app.services.answer_polisher import answer_polisher

logger = get_logger(__name__)

# Debug-mode NDJSON logging configuration
# Logs go to backend/<LOG_DIR>/<DEBUG_LOG_FILE> by default (configurable via env).
BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEBUG_LOG_PATH = BACKEND_ROOT / settings.LOG_DIR / settings.DEBUG_LOG_FILE


def _debug_log(payload: Dict[str, Any]) -> None:
    """Append a single NDJSON line to the debug log. Never raises."""
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Never let debug logging break the request
        pass


class ChatService:
    """Chat orchestration (intent -> retrieval -> response)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _is_complex_query(self, text: str) -> bool:
        if not text:
            return False
        if len(text) > 180:
            return True
        markers = [" and ", ",", "—", ";"]
        if sum(text.count(m) for m in markers) >= 2:
            return True
        topics = ["refund", "shipping", "customs", "payment", "discount", "credit"]
        lowered = text.lower()
        if sum(1 for t in topics if t in lowered) >= 2:
            return True
        return False

    def _is_smalltalk(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        if not t:
            return False

        smalltalk_phrases = {
            "hi",
            "hello",
            "hey",
            "yo",
            "hii",
            "hiii",
            "good morning",
            "good afternoon",
            "good evening",
            "thanks",
            "thank you",
            "thx",
            "ok",
            "okay",
            "cool",
            "great",
            "nice",
            "👍",
            "🙏",
        }
        if t in smalltalk_phrases:
            return True

        # Emoji-only / punctuation-only (no letters/digits) and short.
        if len(t) <= 10 and not re.search(r"[a-z0-9]", t):
            return True

        # Very short and no product/policy intent.
        if len(t) <= 6 and not re.search(r"[0-9]", t):
            if not self._looks_like_product_query(t) and not re.search(r"[?]|refund|shipping|return|policy", t):
                return True

        return False

    def _is_meta_question(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        patterns = [
            r"\b(ai|a\.i\.)\b",
            r"\bare you (an )?ai\b",
            r"\bare you (a )?human\b",
            r"\bwho are you\b",
            r"\bwhat are you\b",
            r"\bwhat can you do\b",
            r"\bhow do you work\b",
            r"\bwhat model\b",
        ]
        if any(re.search(p, t) for p in patterns):
            # Avoid triggering on product terms like "AI" in SKU etc; require conversational framing.
            return bool(re.search(r"\b(are you|who|what|how)\b", t))
        return False

    def _is_general_chat(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        general_patterns = [
            r"\bhow are you\b",
            r"\bwhat'?s up\b",
            r"\btell me a joke\b",
            r"\bmake me laugh\b",
            r"\bfun fact\b",
            r"\bwhat do you think\b",
        ]
        return any(re.search(p, t) for p in general_patterns)

    def _has_store_intent(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        store_keywords = [
            "price",
            "cost",
            "buy",
            "order",
            "wholesale",
            "moq",
            "minimum order",
            "min order",
            "shipping",
            "refund",
            "return",
            "policy",
            "sku",
            "size",
            "gauge",
            "material",
            "color",
            "recommend",
            "show me",
            "find",
            "search",
            "customs",
            "bank transfer",
            "watermark",
            "contact",
            "acha",
            "products",
            "product",
        ]
        if any(k in t for k in store_keywords):
            return True
        # Treat generic "help/support" as store intent when not obviously general chat.
        if re.search(r"\b(help|support)\b", t) and not self._is_general_chat(t) and not self._is_meta_question(t):
            return True
        return False

    def _is_policy_intent(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        policy_keywords = [
            "refund",
            "return",
            "shipping",
            "policy",
            "minimum order",
            "moq",
            "customs",
            "bank transfer",
            "watermark",
            "payment",
            "discount",
            "store credit",
        ]
        return any(k in t for k in policy_keywords)

    async def _general_chat_response(
        self,
        *,
        user_text: str,
        history: List[Dict[str, str]],
    ) -> str:
        model = getattr(settings, "GENERAL_CHAT_MODEL", None) or settings.OPENAI_MODEL
        max_tokens = int(getattr(settings, "GENERAL_CHAT_MAX_TOKENS", 250))
        system = (
            "You are AchaDirect's AI assistant.\n"
            "Have a natural, friendly conversation.\n"
            "STRICT RULES:\n"
            "- Do NOT invent store policies, prices, refunds, shipping rules, or product availability.\n"
            "- If the user asks for products, prices, or store policies, ask a short question to pivot:\n"
            "  'Are you looking for a product recommendation, a SKU price, or a store policy?'\n"
            "- Keep replies concise (1-4 short sentences).\n"
        )
        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
        for m in history[-6:]:
            role = m.get("role")
            content = m.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        return await llm_service.generate_chat_response(messages, temperature=0.5, max_tokens=max_tokens, model=model)

    async def _smalltalk_response(self, *, user_text: str) -> str:
        mode = str(getattr(settings, "SMALLTALK_MODE", "static") or "static").lower()
        if mode != "llm":
            return "Hi! How can I help you today — products, prices, or store policies?"

        model = getattr(settings, "SMALLTALK_MODEL", None) or settings.OPENAI_MODEL
        system = (
            "You are AchaDirect's AI assistant.\n"
            "Reply naturally to a greeting/thanks in 1-2 sentences.\n"
            "Ask what they want to do next: products, SKU price, or store policies.\n"
            "Do NOT mention random policies.\n"
        )
        return await llm_service.generate_chat_response(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_text}],
            temperature=0.6,
            max_tokens=80,
            model=model,
        )

    @staticmethod
    def _is_question_like(text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        if "?" in t:
            return True
        if re.match(r"^(how|what|where|when|why|can|do|does|is|are|will|would|could|should)\b", t):
            return True
        # Treat explicit request statements as question-like to avoid misrouting.
        if re.search(
            r"\b(refund|return|shipping|policy|minimum order|min(?:imum)? order|discount|customs|payment|bank transfer|price|cost|sku)\b",
            t,
        ):
            return True
        if re.match(r"^(please|help|explain|tell me|i want|i need|show me|find|search)\b", t):
            return True
        return False

    def _looks_like_product_query(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        keywords = [
            "show me",
            "recommend",
            "suggest",
            "find",
            "looking for",
            "i need",
            "buy",
            "shop",
            "product",
            "sku",
            "price",
            "cost",
            "barbell",
            "ring",
            "tunnel",
            "stud",
            "piercing",
            "plug",
            "jewelry",
            "labret",
            "clip",
            "belly",
            "nipple",
            "shield",
        ]
        if any(k in lowered for k in keywords):
            return True
        if re.search(r"\b\d{1,2}g\b", lowered):
            return True
        if re.search(r"\b\d+(?:\.\d+)?\s*mm\b", lowered):
            return True
        return False

    def _extract_sku(self, text: str) -> Optional[str]:
        if not text:
            return None
        lowered = text.lower()
        m = re.search(r"\bsku\s*[:#]?\s*([a-z0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*)\b", lowered)
        if m:
            return m.group(1)
        m = re.search(r"\b([a-z0-9]{2,}-[a-z0-9]{2,}(?:-[a-z0-9]{2,})*)\b", lowered)
        if m:
            return m.group(1)
        return None

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
        cards: List[ProductCard] = []
        for p in products:
            cards.append(
                ProductCard(
                    id=p.id,
                    object_id=p.object_id,
                    sku=p.sku,
                    legacy_sku=p.legacy_sku or [],
                    name=p.name,
                    description=p.description,
                    price=p.price,
                    currency=p.currency,
                    stock_status=p.stock_status,
                    image_url=p.image_url,
                    product_url=p.product_url,
                    attributes=p.attributes or {},
                )
            )
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
        await self.db.commit()
        await self.db.refresh(user)
        return user

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
            if existing:
                return existing

        conversation = Conversation(user_id=user.id)
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def save_message(self, conversation_id: int, role: str, content: str) -> None:
        msg = Message(conversation_id=conversation_id, role=role, content=content)
        self.db.add(msg)
        await self.db.commit()

    async def get_history(self, conversation_id: int, limit: int = 5) -> List[Dict[str, str]]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        msgs = result.scalars().all()
        return [{"role": m.role, "content": m.content} for m in reversed(msgs)]

    async def search_knowledge(
        self,
        query_text: str,
        query_embedding: List[float],
        limit: int = 10,
        must_tags: Optional[List[str]] = None,
        boost_tags: Optional[List[str]] = None,
        run_id: Optional[str] = None,
    ) -> Tuple[List[KnowledgeSource], Optional[float]]:
        """
        Vector search over knowledge base with optional tag constraints.
        Returns sources and the best (lowest) cosine distance.
        """
        tag_join_needed = bool(must_tags or boost_tags)

        distance_col = KnowledgeEmbedding.embedding.cosine_distance(query_embedding).label("distance")

        stmt = (
            select(
                KnowledgeEmbedding.id,
                KnowledgeEmbedding.chunk_text,
                KnowledgeEmbedding.article_id,
                KnowledgeEmbedding.chunk_id,
                KnowledgeArticle.title,
                KnowledgeArticle.category,
                KnowledgeArticle.url,
                distance_col,
            )
            .join(KnowledgeArticle, KnowledgeEmbedding.article_id == KnowledgeArticle.id)
        )

        if tag_join_needed:
            stmt = stmt.join(KnowledgeChunk, KnowledgeChunk.id == KnowledgeEmbedding.chunk_id)
            stmt = stmt.outerjoin(KnowledgeChunkTag, KnowledgeChunkTag.chunk_id == KnowledgeChunk.id)

        if must_tags or tag_join_needed:
            stmt = stmt.group_by(
                KnowledgeEmbedding.id,
                KnowledgeEmbedding.chunk_text,
                KnowledgeEmbedding.article_id,
                KnowledgeEmbedding.chunk_id,
                KnowledgeArticle.title,
                KnowledgeArticle.category,
                KnowledgeArticle.url,
                distance_col,
            )

        if must_tags:
            required_count = len(set(must_tags))
            stmt = stmt.having(
                func.count(func.distinct(KnowledgeChunkTag.tag)).filter(KnowledgeChunkTag.tag.in_(must_tags))
                == required_count
            )

        if boost_tags:
            boost_case = func.max(case((KnowledgeChunkTag.tag.in_(boost_tags), 1), else_=0)).label("boost_match")
            stmt = stmt.add_columns(boost_case).order_by(distance_col, boost_case.desc())
        else:
            stmt = stmt.order_by(distance_col)

        stmt = stmt.limit(limit)

        result = await self.db.execute(stmt)
        rows: Sequence[Any] = result.all()

        logger.info(
            f"[RAG] knowledge retrieval: threshold={settings.KNOWLEDGE_DISTANCE_THRESHOLD} limit={limit} run_id={run_id}"
        )

        sources: List[KnowledgeSource] = []
        best_distance: Optional[float] = None

        for idx, row in enumerate(rows):
            (
                emb_id,
                chunk_text,
                article_id,
                chunk_id,
                title,
                category,
                url,
                distance,
                *maybe_boost,
            ) = row
            if best_distance is None:
                best_distance = float(distance)

            similarity = 1 - float(distance)

            if idx < 3:
                preview = (chunk_text or "")[:200].replace("\n", " ")
                logger.info(f"[RAG] top{idx+1} title={title!r} distance={float(distance):.4f} preview={preview!r}")

            sources.append(
                KnowledgeSource(
                    source_id=str(emb_id),
                    chunk_id=str(chunk_id) if chunk_id else None,
                    title=title,
                    content_snippet=(chunk_text or "")[: settings.RAG_MAX_CHUNK_CHARS_FOR_CONTEXT],
                    category=category,
                    relevance=similarity,
                    url=url,
                    distance=float(distance),
                )
            )

            # #region agent log
            if run_id and idx < 3:
                try:
                    _debug_log(
                        {
                            "sessionId": "debug-session",
                            "runId": run_id,
                            "hypothesisId": "HK",
                            "location": "chat_service.search_knowledge:top_result",
                            "message": "top knowledge chunk",
                            "data": {
                                "rank": idx + 1,
                                "article_id": str(article_id),
                                "title": title,
                                "distance": float(distance),
                                "threshold": settings.KNOWLEDGE_DISTANCE_THRESHOLD,
                                "snippet": (chunk_text or "")[:200],
                            },
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                except Exception:
                    pass
            # #endregion

        return sources, best_distance

    async def search_products(
        self,
        query_embedding: List[float],
        limit: int = 10,
        run_id: Optional[str] = None,
    ) -> Tuple[List[ProductCard], List[float], Optional[float], Dict[str, float]]:
        """
        Vector search over product embeddings.
        Returns product cards and best (lowest) cosine distance.
        """
        distance_col = ProductEmbedding.embedding.cosine_distance(query_embedding).label("distance")

        model = getattr(settings, "PRODUCT_EMBEDDING_MODEL", settings.EMBEDDING_MODEL)
        probe_stmt = (
            select(ProductEmbedding.product_id, distance_col)
            .join(Product, Product.id == ProductEmbedding.product_id)
            .where(Product.is_active.is_(True))
            .where(or_(ProductEmbedding.model.is_(None), ProductEmbedding.model == model))
            .order_by(distance_col)
            .limit(limit)
        )
        probe_result = await self.db.execute(probe_stmt)
        probe_rows: Sequence[Any] = probe_result.all()

        if not probe_rows:
            return [], [], None, {}

        distances = [float(row.distance) for row in probe_rows]
        best_distance = distances[0] if distances else None
        product_id_order = [row.product_id for row in probe_rows]
        distance_by_id = {str(row.product_id): float(row.distance) for row in probe_rows}

        # Fetch full product data after probe to keep the probe fast
        products_stmt = select(Product).where(Product.id.in_(product_id_order))
        products_result = await self.db.execute(products_stmt)
        products_by_id = {p.id: p for p in products_result.scalars().all()}

        product_cards: List[ProductCard] = []
        for idx, pid in enumerate(product_id_order):
            product = products_by_id.get(pid)
            if not product:
                continue
            product_cards.append(
                ProductCard(
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
                    attributes=product.attributes or {},
                )
            )

            # #region agent log
            if run_id and idx < 3:
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
                                "product_id": str(product.id),
                                "name": product.name,
                                "distance": distances[idx] if idx < len(distances) else None,
                                "threshold": settings.PRODUCT_DISTANCE_THRESHOLD,
                            },
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                except Exception:
                    pass
            # #endregion

        return product_cards, distances[:5], best_distance, distance_by_id

    async def _rerank_knowledge_with_cohere(
        self,
        *,
        query: str,
        candidates: List[KnowledgeSource],
        run_id: str,
    ) -> List[KnowledgeSource]:
        if not candidates:
            return []

        max_chars = settings.RAG_MAX_DOC_CHARS_FOR_RERANK
        documents: List[str] = []
        for c in candidates[: settings.RAG_RETRIEVE_TOPK_KNOWLEDGE]:
            doc = f"{c.title}\n{c.category or ''}\n{(c.content_snippet or '')[:max_chars]}"
            documents.append(doc[:max_chars])

        rerank_results = await rerank_service.rerank(
            query=query,
            documents=documents,
            top_n=settings.RAG_RERANK_TOPN,
            model=settings.RAG_COHERE_RERANK_MODEL,
        )

        if not rerank_results:
            # Skip or failure => keep original ordering
            self._log_event(
                run_id=run_id,
                location="chat_service.rag.rerank.cohere",
                data={
                    "skipped_or_failed": True,
                    "reason": "no_results",
                    "selected_ids": [c.source_id for c in candidates[: settings.RAG_RERANK_TOPN]],
                },
            )
            selected = candidates[: settings.RAG_RERANK_TOPN]
            for c in selected:
                c.query_hint = query
            return selected

        # Rerank quality gate: if Cohere scores are near-zero, prefer distance ordering.
        top_scores = [float(r.relevance_score) for r in rerank_results[: settings.RAG_RERANK_TOPN]]
        above_count = sum(1 for s in top_scores if s >= settings.RAG_RERANK_MIN_SCORE)
        gate_fallback = above_count < settings.RAG_RERANK_MIN_SCORE_COUNT
        self._log_event(
            run_id=run_id,
            location="chat_service.rag.rerank.gate",
            data={
                "min_score": settings.RAG_RERANK_MIN_SCORE,
                "min_score_count": settings.RAG_RERANK_MIN_SCORE_COUNT,
                "above_count": above_count,
                "top_scores": top_scores,
                "decision": "fallback_to_distance" if gate_fallback else "accept_rerank",
            },
        )
        if gate_fallback:
            selected = candidates[: settings.RAG_RERANK_TOPN]
            for c in selected:
                c.query_hint = query
            return selected

        # Hybrid selection: keep strong rerank hits (precision) + fill by distance (coverage).
        selected: List[KnowledgeSource] = []
        used_keys: set[str] = set()

        def _key(c: KnowledgeSource) -> str:
            return c.chunk_id or c.source_id

        strong_hits = [r for r in rerank_results if float(r.relevance_score) >= settings.RAG_RERANK_MIN_SCORE]
        if not strong_hits:
            strong_hits = rerank_results[:1]

        for r in strong_hits[: settings.RAG_RERANK_TOPN]:
            if 0 <= r.index < len(candidates):
                c = candidates[r.index]
                c.rerank_score = float(r.relevance_score)
                c.query_hint = query
                k = _key(c)
                if k in used_keys:
                    continue
                selected.append(c)
                used_keys.add(k)

        for c in candidates:
            if len(selected) >= settings.RAG_RERANK_TOPN:
                break
            k = _key(c)
            if k in used_keys:
                continue
            c.query_hint = query
            selected.append(c)
            used_keys.add(k)

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.rerank.cohere",
            data={
                "accepted": True,
                "top": [
                    {"source_id": s.source_id, "rerank_score": s.rerank_score}
                    for s in selected[: settings.RAG_RERANK_TOPN]
                ],
            },
        )
        return selected

    async def _decompose_query(self, *, question: str, run_id: str) -> List[str]:
        """
        Decompose a complex user question into 4-8 focused sub-questions (strict JSON).
        Falls back to an empty list if decomposition fails.
        """
        system_prompt = (
            "You decompose a complex customer question into short, focused sub-questions that can be answered from a FAQ.\n"
            "Return STRICT JSON: {\"sub_questions\": [\"...\", ...]}.\n"
            "Rules:\n"
            "- 4 to 8 sub_questions\n"
            "- Each sub_question must be a standalone question\n"
            "- Avoid duplicates, keep them specific\n"
            "- Do NOT include any extra keys\n"
        )

        try:
            data = await llm_service.generate_chat_json(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                model=settings.RAG_DECOMPOSE_MODEL or settings.OPENAI_MODEL,
                temperature=0.0,
                max_tokens=300,
            )
            raw = data.get("sub_questions", [])
            if not isinstance(raw, list):
                raw = []
            sub_questions: List[str] = []
            seen: set[str] = set()
            for item in raw:
                if not isinstance(item, str):
                    continue
                q = item.strip()
                if not q:
                    continue
                key = q.lower()
                if key in seen:
                    continue
                seen.add(key)
                sub_questions.append(q)
                if len(sub_questions) >= settings.RAG_DECOMPOSE_MAX_SUBQUESTIONS:
                    break
        except Exception as e:
            sub_questions = []
            self._log_event(
                run_id=run_id,
                location="chat_service.rag.decompose",
                data={"error": str(e), "sub_questions": []},
            )
            return []

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.decompose",
            data={"sub_questions": sub_questions},
        )
        return sub_questions

    async def _retrieve_knowledge_for_query(
        self, *, query_text: str, run_id: str
    ) -> Tuple[List[KnowledgeSource], Optional[float]]:
        query_embedding = await llm_service.generate_embedding(query_text)
        sources, best = await self.search_knowledge(
            query_text=query_text,
            query_embedding=query_embedding,
            limit=settings.RAG_RETRIEVE_TOPK_KNOWLEDGE,
            must_tags=None,
            boost_tags=None,
            run_id=run_id,
        )
        if not sources:
            sources = await self.keyword_fallback(query_text, limit=settings.RAG_RETRIEVE_TOPK_KNOWLEDGE)
            best = None
        return sources, best

    async def _verify_answerable(
        self,
        *,
        question: str,
        knowledge_sources: List[KnowledgeSource],
        product_cards: List[ProductCard],
        run_id: str,
    ) -> Dict[str, Any]:
        verifier_model = settings.RAG_VERIFY_MODEL or settings.OPENAI_MODEL

        max_verify_chunks = max(1, int(getattr(settings, "RAG_VERIFY_MAX_KNOWLEDGE_CHUNKS", settings.RAG_RERANK_TOPN)))
        provided_chunk_ids = {str(s.source_id) for s in knowledge_sources[:max_verify_chunks]}

        chunks_text = "\n\n".join(
            [
                (
                    f"ID: {s.source_id}\n"
                    f"TITLE: {s.title}\n"
                    f"CATEGORY: {s.category or ''}\n"
                    f"URL: {s.url or ''}\n"
                    f"TEXT: {(s.content_snippet or '')[: settings.RAG_MAX_CHUNK_CHARS_FOR_CONTEXT]}"
                )
                for s in knowledge_sources[:max_verify_chunks]
            ]
        )

        products_text = "\n".join(
            [
                f"- {p.name} (sku={p.sku}, price={p.price} {p.currency})"
                for p in product_cards[: min(5, len(product_cards))]
            ]
        )

        system_prompt = (
            "You are a STRICT VERIFIER for a RAG-based chatbot.\n\n"
            "Your job is NOT to simply decide yes/no.\n"
            "Your PRIMARY responsibility is to analyze a user question, decompose it into distinct topics,\n"
            "and determine which topics are answerable from the provided context and which are not.\n\n"
            "You must ALWAYS reason at the topic level.\n\n"
            "========================\n"
            "PROCESS (MANDATORY)\n"
            "========================\n\n"
            "STEP 1 — Decompose the question\n"
            "- Identify ALL distinct topics or requirements implied by the question.\n"
            "- Treat each topic independently.\n"
            "- Examples of topics: refunds, discounts, shipping costs, customs fees, payment methods, images, custom items, sterilized items.\n\n"
            "STEP 2 — Evaluate each topic against the context\n"
            "For EACH topic:\n"
            "- If the context EXPLICITLY contains sufficient information to answer it:\n"
            "  - Mark it as answerable\n"
            "  - List the supporting_chunk_ids that prove it\n"
            "- If the context does NOT contain sufficient information:\n"
            "  - Mark it as missing\n"
            "  - Write ONE clear clarification question for that topic\n\n"
            "STEP 3 — Populate structured results\n"
            "- Populate answerable_parts for EVERY topic that is supported\n"
            "- Populate missing_parts for EVERY topic that is not supported\n"
            "- missing_parts MUST be ordered by importance to the user:\n"
            "  1) refunds / returns / refused delivery\n"
            "  2) shipping costs / liabilities\n"
            "  3) payment fees or obligations\n"
            "  4) product availability or customization\n"
            "  5) images / marketing / low-risk items\n\n"
            "STEP 4 — Set global flags\n"
            "- answerable = true ONLY if there are NO missing_parts\n"
            "- answerable = false if ANY missing_parts exist\n"
            "- answer_type should reflect the dominant source of information:\n"
            "  - \"knowledge\", \"product\", or \"mixed\"\n\n"
            "========================\n"
            "STRICT RULES\n"
            "========================\n\n"
            "- supporting_chunk_ids MUST be a subset of the provided chunk IDs\n"
            "- NEVER invent policies or facts not present in the context\n"
            "- NEVER answer from general knowledge\n"
            "- NEVER merge topics together — keep them explicit\n"
            "- NEVER return BOTH answerable_parts AND missing_parts empty\n"
            "- If at least ONE topic is supported, answerable_parts MUST NOT be empty\n"
            "- If NO topics are supported, ALL topics must appear in missing_parts\n"
            "- If the question is multi-topic, partial answers are REQUIRED\n"
            "- The verifier must be strict but USEFUL\n\n"
            "========================\n"
            "OUTPUT FORMAT (STRICT)\n"
            "========================\n\n"
            "Return ONLY valid JSON with EXACTLY these keys:\n\n"
            "{\n"
            "  \"answerable\": boolean,\n"
            "  \"answer_type\": \"knowledge\" | \"product\" | \"mixed\",\n"
            "  \"supporting_chunk_ids\": string[],\n"
            "  \"missing_info_question\": string | null,\n"
            "  \"answerable_parts\": [\n"
            "    {\n"
            "      \"topic\": string,\n"
            "      \"supporting_chunk_ids\": string[]\n"
            "    }\n"
            "  ],\n"
            "  \"missing_parts\": [\n"
            "    {\n"
            "      \"topic\": string,\n"
            "      \"missing_info_question\": string\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Notes:\n"
            "- supporting_chunk_ids (top-level) should be the UNION of all answerable_parts chunk IDs\n"
            "- missing_info_question (top-level) should be ONE high-priority clarification question\n"
            "  derived from the FIRST item in missing_parts, or null if fully answerable\n"
        )

        user_prompt = (
            f"Question: {question}\n\n"
            f"Knowledge Chunks:\n{chunks_text or '[none]'}\n\n"
            f"Product Candidates:\n{products_text or '[none]'}\n"
        )

        def _normalize_decision(raw: Any) -> Dict[str, Any]:
            decision: Dict[str, Any] = raw if isinstance(raw, dict) else {}

            answer_type = (decision.get("answer_type") or "knowledge").lower()
            if answer_type not in {"knowledge", "product", "mixed"}:
                answer_type = "knowledge"

            answerable_parts = decision.get("answerable_parts")
            missing_parts = decision.get("missing_parts")
            if not isinstance(answerable_parts, list):
                answerable_parts = []
            if not isinstance(missing_parts, list):
                missing_parts = []

            normalized_answerable_parts: List[Dict[str, Any]] = []
            for p in answerable_parts:
                if not isinstance(p, dict):
                    continue
                topic = p.get("topic")
                ids = p.get("supporting_chunk_ids")
                if not isinstance(topic, str) or not topic.strip():
                    continue
                if not isinstance(ids, list):
                    ids = []
                filtered_ids = [str(x) for x in ids if str(x) in provided_chunk_ids]
                if not filtered_ids:
                    continue
                normalized_answerable_parts.append({"topic": topic.strip(), "supporting_chunk_ids": filtered_ids})

            normalized_missing_parts: List[Dict[str, Any]] = []
            for p in missing_parts:
                if not isinstance(p, dict):
                    continue
                topic = p.get("topic")
                mq = p.get("missing_info_question")
                if not isinstance(topic, str) or not topic.strip():
                    continue
                if not isinstance(mq, str) or not mq.strip():
                    continue
                normalized_missing_parts.append({"topic": topic.strip(), "missing_info_question": mq.strip()})

            supporting_union: List[str] = []
            seen_ids: set[str] = set()
            for p in normalized_answerable_parts:
                for cid in p.get("supporting_chunk_ids", []):
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        supporting_union.append(cid)

            # Ensure we never return both lists empty.
            if not normalized_answerable_parts and not normalized_missing_parts:
                normalized_missing_parts = [
                    {
                        "topic": "general",
                        "missing_info_question": "Which specific part should I answer first (refunds, shipping costs, payment fees, or discounts)?",
                    }
                ]

            normalized_answerable = len(normalized_missing_parts) == 0
            top_missing_question = normalized_missing_parts[0]["missing_info_question"] if normalized_missing_parts else None

            return {
                "answerable": bool(normalized_answerable),
                "answer_type": answer_type,
                "supporting_chunk_ids": supporting_union,
                "missing_info_question": top_missing_question,
                "answerable_parts": normalized_answerable_parts,
                "missing_parts": normalized_missing_parts,
            }

        try:
            decision_raw = await llm_service.generate_chat_json(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=verifier_model,
                temperature=0.0,
                max_tokens=600,
            )
            decision = _normalize_decision(decision_raw)
        except Exception as e:
            logger.error(f"Verifier failed: {e}")
            decision = _normalize_decision(
                {
                    "answerable": False,
                    "answer_type": "knowledge",
                    "supporting_chunk_ids": [],
                    "missing_info_question": None,
                    "answerable_parts": [],
                    "missing_parts": [
                        {
                            "topic": "general",
                            "missing_info_question": "Which specific part should I answer first (refunds, shipping costs, payment fees, or discounts)?",
                        }
                    ],
                }
            )

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.verify",
            data={"decision": decision},
        )
        return decision

    async def keyword_fallback(self, query_text: str, limit: int = 5) -> List[KnowledgeSource]:
        """
        Keyword OR search over knowledge chunks when vector search is weak.
        Scores chunks by how many query keywords they contain.
        """
        # Very small stopword list for English
        stopwords = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "to",
            "for",
            "of",
            "in",
            "on",
            "at",
            "by",
            "with",
            "is",
            "are",
            "was",
            "were",
        }
        tokens = [t.lower() for t in query_text.replace(",", " ").replace(".", " ").split()]
        keywords = [t for t in tokens if len(t) >= 3 and t not in stopwords][:6]

        if not keywords:
            return []

        conditions = [KnowledgeChunk.chunk_text.ilike(f"%{kw}%") for kw in keywords]

        # Build a per-row match count expression without using SQL aggregate functions
        score_expr = None
        for cond in conditions:
            term = case((cond, 1), else_=0)
            score_expr = term if score_expr is None else score_expr + term

        match_count = score_expr.label("match_count") if score_expr is not None else None

        stmt = (
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.chunk_text,
                KnowledgeArticle.id.label("article_id"),
                KnowledgeArticle.title,
                KnowledgeArticle.category,
                KnowledgeArticle.url,
                match_count,
            )
            .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
            .where(or_(*conditions))
        )

        if match_count is not None:
            stmt = stmt.order_by(match_count.desc(), KnowledgeChunk.id)

        stmt = stmt.limit(limit)

        result = await self.db.execute(stmt)
        rows = result.all()

        sources: List[KnowledgeSource] = []
        for chunk_id, chunk_text, article_id, title, category, url, match_value in rows:
            relevance = float(match_value or 0) / max(len(keywords), 1)
            sources.append(
                KnowledgeSource(
                    source_id=str(chunk_id),
                    chunk_id=str(chunk_id),
                    title=title,
                    content_snippet=(chunk_text or "")[: settings.RAG_MAX_CHUNK_CHARS_FOR_CONTEXT],
                    category=category,
                    relevance=relevance,
                    url=url,
                    distance=None,
                )
            )
        return sources

    async def synthesize_answer(self, question: str, sources: List[KnowledgeSource]) -> str:
        if not sources:
            return (
                "I don't have enough information in my knowledge base to answer that yet. "
                "Try asking another question or rephrasing."
            )

        context = "\n\n".join(
            [
                f"ID: {s.source_id}\nTITLE: {s.title}\nTEXT: {s.content_snippet}"
                for s in sources[: min(5, len(sources))]
            ]
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a customer support assistant for AchaDirect. Answer using ONLY the provided knowledge context. "
                    "If the answer is not in the context, say you don't have enough information. "
                    "Do not echo or restate the user's question. "
                    "Do not include a Sources/References section in your reply."
                ),
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ]
        try:
            return await llm_service.generate_chat_response(messages, temperature=0.2)
        except Exception as e:
            logger.error(f"LLM response generation failed: {e}")
            return "I'm having trouble generating an answer right now. Please try again."

    async def synthesize_partial_answer(
        self,
        *,
        original_question: str,
        sources: List[KnowledgeSource],
        answerable_topics: List[str],
        missing_question: str,
    ) -> str:
        if not sources:
            return missing_question

        topics_text = ", ".join(answerable_topics[:6]) if answerable_topics else "the supported parts"
        context = "\n\n".join(
            [
                f"ID: {s.source_id}\nTITLE: {s.title}\nURL: {s.url or ''}\nTEXT: {s.content_snippet}"
                for s in sources[: min(6, len(sources))]
            ]
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a careful RAG assistant. Write ONLY what is explicitly supported by the context.\n"
                    "If a detail is not in the context, say it is not specified.\n"
                    "Do not invent policies.\n"
                    "Do not echo the user's question.\n"
                    "Do not include a Sources/References section in your reply.\n"
                    "Output a short section titled 'What I found' with 2-6 bullet points."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original question:\n{original_question}\n\n"
                    f"Focus topics:\n{topics_text}\n\n"
                    f"Context:\n{context}\n"
                ),
            },
        ]

        try:
            found = await llm_service.generate_chat_response(messages, temperature=0.2)
        except Exception as e:
            logger.error(f"Partial answer generation failed: {e}")
            found = "What I found:\n- I couldn't generate a summary from the retrieved context."

        return f"{found}\n\nOne question to confirm:\n{missing_question}"

    def _strip_sources_block(self, text: str) -> str:
        """Remove any model- or server-appended Sources/References section from reply_text."""
        if not text:
            return text
        lowered = text.lower()
        markers = ["\n\nsources:\n", "\nsources:\n", "\n\nreferences:\n", "\nreferences:\n"]
        for marker in markers:
            idx = lowered.find(marker.strip("\n"))
            if idx != -1:
                return text[:idx].rstrip()
        return text

    async def process_chat(self, req: ChatRequest) -> ChatResponse:
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        history = await self.get_history(conversation.id)

        run_id = f"chat-{int(time.time() * 1000)}"

        _debug_log(
            {
                "sessionId": "debug-session",
                "runId": run_id,
                "hypothesisId": "H0",
                "location": "chat_service.process_chat:start",
                "message": "process_chat start",
                "data": {"user_id": req.user_id, "message": req.message},
                "timestamp": int(time.time() * 1000),
            }
        )

        text = req.message or ""
        if bool(getattr(settings, "SMALLTALK_ENABLED", True)) and self._is_smalltalk(text):
            reply_text = await self._smalltalk_response(user_text=text)
            follow_ups = ["Browse products", "Check a SKU price", "Shipping & policies"]
            self._log_event(
                run_id=run_id,
                location="chat_service.route_selected",
                data={"route": "smalltalk", "smalltalk_detected": True},
            )
            await self.save_message(conversation.id, MessageRole.USER, req.message)
            await self.save_message(conversation.id, MessageRole.ASSISTANT, reply_text)
            return ChatResponse(
                conversation_id=conversation.id,
                reply_text=reply_text,
                product_carousel=[],
                follow_up_questions=follow_ups,
                intent="smalltalk",
                sources=[],
            )

        # Meta / general chat (LLM-only, no retrieval/verifier).
        if self._is_meta_question(text) or self._is_general_chat(text):
            try:
                reply_text = await self._general_chat_response(user_text=text, history=history)
            except Exception as e:
                logger.error(f"general_chat generation failed: {e}")
                reply_text = "I'm an AI assistant. Are you looking for a product recommendation, a SKU price, or a store policy?"
            self._log_event(
                run_id=run_id,
                location="chat_service.route_selected",
                data={"route": "general_chat", "meta_detected": self._is_meta_question(text)},
            )
            await self.save_message(conversation.id, MessageRole.USER, req.message)
            await self.save_message(conversation.id, MessageRole.ASSISTANT, reply_text)
            return ChatResponse(
                conversation_id=conversation.id,
                reply_text=self._strip_sources_block(reply_text),
                product_carousel=[],
                follow_up_questions=["Browse products", "Check a SKU price", "Shipping & policies"],
                intent="general_chat",
                sources=[],
            )

        requested_currency = currency_service.extract_requested_currency(req.message or "")
        default_display_currency = (
            getattr(settings, "PRICE_DISPLAY_CURRENCY", None)
            or getattr(settings, "BASE_CURRENCY", None)
            or "USD"
        )
        default_display_currency = str(default_display_currency).upper()
        if requested_currency and not currency_service.supports(requested_currency):
            requested_currency = None
        target_currency = (requested_currency or default_display_currency).upper()

        looks_like_product = self._looks_like_product_query(text)
        sku_token = self._extract_sku(text)
        product_topk = int(getattr(settings, "PRODUCT_SEARCH_TOPK", settings.RAG_RETRIEVE_TOPK_PRODUCT))
        is_question_like = self._is_question_like(req.message or "")
        has_store_intent = self._has_store_intent(text)
        is_policy_intent = self._is_policy_intent(text)

        is_complex = self._is_complex_query(req.message)
        max_sub_questions = int(getattr(settings, "RAG_MAX_SUB_QUESTIONS", 4))
        self._log_event(
            run_id=run_id,
            location="chat_service.rag.complexity_check",
            data={
                "is_complex": is_complex,
                "len": len(req.message or ""),
                "max_sub_questions": max_sub_questions,
            },
        )

        # Low-signal freeform text should not trigger random KB clarifications.
        if not is_question_like and not looks_like_product and not sku_token:
            if has_store_intent:
                reply_text = "I can help you find products or answer store questions — what are you looking for?"
                route = "fallback_general"
            else:
                try:
                    reply_text = await self._general_chat_response(user_text=text, history=history)
                except Exception:
                    reply_text = "Sure — what would you like to chat about?"
                route = "general_chat"

            follow_ups = ["Browse products", "Check a SKU price", "Shipping & policies"]
            self._log_event(
                run_id=run_id,
                location="chat_service.route_selected",
                data={"route": route, "reason": "low_signal_non_question"},
            )
            await self.save_message(conversation.id, MessageRole.USER, req.message)
            await self.save_message(conversation.id, MessageRole.ASSISTANT, reply_text)
            return ChatResponse(
                conversation_id=conversation.id,
                reply_text=self._strip_sources_block(reply_text),
                product_carousel=[],
                follow_up_questions=follow_ups,
                intent=route,
                sources=[],
            )

        # SKU shortcut (must-have): direct DB lookup without embeddings.
        if sku_token:
            sku_cards = await self._search_products_by_exact_sku(sku=sku_token, limit=product_topk)
            if sku_cards:
                self._log_event(
                    run_id=run_id,
                    location="chat_service.product.sku_shortcut",
                    data={"matched_sku": sku_token, "count": len(sku_cards)},
                )

                price_intent = bool(re.search(r"\b(price|cost)\b", (req.message or "").lower()))
                if price_intent:
                    p0 = sku_cards[0]
                    converted = currency_service.convert(
                        float(p0.price),
                        from_currency=str(p0.currency or settings.BASE_CURRENCY),
                        to_currency=target_currency,
                    )
                    reply_text = f"The price of {p0.sku} is {round(float(converted.amount), 2)} {converted.currency}."
                else:
                    reply_text = "Here are some products that might help:"

                reply_text = self._strip_sources_block(reply_text)
                sku_cards = currency_service.convert_product_cards(sku_cards, to_currency=target_currency)
                await self.save_message(conversation.id, MessageRole.USER, req.message)
                await self.save_message(conversation.id, MessageRole.ASSISTANT, reply_text)
                return ChatResponse(
                    conversation_id=conversation.id,
                    reply_text=reply_text,
                    product_carousel=sku_cards,
                    follow_up_questions=[],
                    intent="product",
                    sources=[],
                )

        sub_questions: List[str] = []
        original_embedding = await llm_service.generate_embedding(req.message)

        product_cards_all: List[ProductCard] = []
        product_top_distances: List[float] = []
        product_best: Optional[float] = None
        product_distance_by_id: Dict[str, float] = {}

        # Policy keywords: allow skipping product search to avoid irrelevant work.
        if not (is_policy_intent and not looks_like_product):
            # Product retrieval once, before verifier (and can short-circuit routing).
            product_retrieve_k = max(product_topk * 5, product_topk)
            product_cards_all, product_top_distances, product_best, product_distance_by_id = await self.search_products(
                query_embedding=original_embedding,
                limit=product_retrieve_k,
                run_id=run_id,
            )

        jewelry_type_filter = self._infer_jewelry_type_filter(req.message)
        if jewelry_type_filter:
            filtered: List[ProductCard] = []
            for p in product_cards_all:
                jt = None
                if isinstance(p.attributes, dict):
                    jt = p.attributes.get("jewelry_type")
                if jt is not None and str(jt).strip().lower() == jewelry_type_filter.lower():
                    filtered.append(p)
            product_cards_filtered = filtered
        else:
            product_cards_filtered = product_cards_all

        product_cards = product_cards_filtered[:product_topk]
        product_best_for_gate: Optional[float] = None
        if product_cards:
            bests = []
            for p in product_cards:
                d = product_distance_by_id.get(str(p.id))
                if d is not None:
                    bests.append(float(d))
            product_best_for_gate = min(bests) if bests else product_best

        strict = float(getattr(settings, "PRODUCT_DISTANCE_STRICT", 0.35))
        loose = float(getattr(settings, "PRODUCT_DISTANCE_LOOSE", 0.45))
        product_gate_decision = "none"
        if looks_like_product and product_best_for_gate is not None:
            if product_best_for_gate <= strict:
                product_gate_decision = "strict"
            elif product_best_for_gate <= loose:
                product_gate_decision = "loose"

        self._log_event(
            run_id=run_id,
            location="chat_service.product.route_gate",
            data={
                "looks_like_product": looks_like_product,
                "jewelry_type_filter": jewelry_type_filter,
                "product_best": product_best,
                "product_best_for_gate": product_best_for_gate,
                "strict": strict,
                "loose": loose,
                "decision": product_gate_decision,
                "count": len(product_cards),
            },
        )

        if product_gate_decision in {"strict", "loose"} and product_cards:
            reply_text = "Here are some products that might help:"
            reply_text = self._strip_sources_block(reply_text)
            product_cards = currency_service.convert_product_cards(product_cards, to_currency=target_currency)
            await self.save_message(conversation.id, MessageRole.USER, req.message)
            await self.save_message(conversation.id, MessageRole.ASSISTANT, reply_text)
            return ChatResponse(
                conversation_id=conversation.id,
                reply_text=reply_text,
                product_carousel=product_cards,
                follow_up_questions=[],
                intent="product",
                sources=[],
            )

        # Only decompose for the knowledge pipeline (after product gating).
        if is_complex:
            sub_questions = await self._decompose_query(question=req.message, run_id=run_id)
            sub_questions = sub_questions[:max_sub_questions]
        queries = [req.message] + sub_questions
        # De-dup while preserving order
        seen_q: set[str] = set()
        queries = [q for q in queries if not (q.lower() in seen_q or seen_q.add(q.lower()))]

        def _choose_better(existing: Optional[KnowledgeSource], new: KnowledgeSource) -> KnowledgeSource:
            if existing is None:
                return new
            if existing.distance is None and new.distance is None:
                chosen = existing
            if existing.distance is None and new.distance is not None:
                chosen = new
            if existing.distance is not None and new.distance is None:
                chosen = existing
            else:
                chosen = (
                    new
                    if (new.distance is not None and existing.distance is not None and new.distance < existing.distance)
                    else existing
                )

            # Preserve rerank metadata if it exists on either candidate.
            other = new if chosen is existing else existing
            if getattr(chosen, "rerank_score", None) is None and getattr(other, "rerank_score", None) is not None:
                chosen.rerank_score = other.rerank_score
            if getattr(chosen, "query_hint", None) is None and getattr(other, "query_hint", None) is not None:
                chosen.query_hint = other.query_hint
            return chosen

        per_query_keep = max(1, int(getattr(settings, "RAG_PER_QUERY_KEEP", 1)))
        coverage_by_key: Dict[str, KnowledgeSource] = {}
        coverage_keys_in_order: List[str] = []
        pool_by_key: Dict[str, KnowledgeSource] = {}
        kept_per_query: List[Dict[str, Any]] = []
        per_query_best: List[Optional[float]] = []

        for q in queries:
            if q == req.message:
                sources_q, best_q = await self.search_knowledge(
                    query_text=req.message,
                    query_embedding=original_embedding,
                    limit=settings.RAG_RETRIEVE_TOPK_KNOWLEDGE,
                    must_tags=None,
                    boost_tags=None,
                    run_id=run_id,
                )
                if not sources_q:
                    sources_q = await self.keyword_fallback(req.message, limit=settings.RAG_RETRIEVE_TOPK_KNOWLEDGE)
                    best_q = None
            else:
                sources_q, best_q = await self._retrieve_knowledge_for_query(query_text=q, run_id=run_id)
            per_query_best.append(best_q)
            # Coverage-first merge uses distance ordering per query (no per-subquestion rerank).
            kept_ids: List[str] = []
            for s in sources_q[:per_query_keep]:
                s.query_hint = q
                key = s.chunk_id or s.source_id
                if key not in coverage_by_key:
                    coverage_keys_in_order.append(key)
                coverage_by_key[key] = _choose_better(coverage_by_key.get(key), s)
                kept_ids.append(str(s.source_id))

            kept_per_query.append({"query": q, "kept_source_ids": kept_ids})

            for s in sources_q[per_query_keep:]:
                s.query_hint = q
                key = s.chunk_id or s.source_id
                if key in coverage_by_key:
                    continue
                pool_by_key[key] = _choose_better(pool_by_key.get(key), s)

        coverage_sources: List[KnowledgeSource] = [coverage_by_key[k] for k in coverage_keys_in_order if k in coverage_by_key]
        pool_sources = sorted(
            pool_by_key.values(),
            key=lambda s: (s.distance is None, s.distance if s.distance is not None else 9999.0),
        )

        merged: List[KnowledgeSource] = []
        merged_keys: set[str] = set()
        for s in coverage_sources:
            key = s.chunk_id or s.source_id
            if key in merged_keys:
                continue
            merged.append(s)
            merged_keys.add(key)

        for s in pool_sources:
            if len(merged) >= settings.RAG_RETRIEVE_TOPK_KNOWLEDGE:
                break
            key = s.chunk_id or s.source_id
            if key in merged_keys:
                continue
            merged.append(s)
            merged_keys.add(key)

        knowledge_sources = merged
        knowledge_best = min([d for d in per_query_best if d is not None], default=None)

        knowledge_top_distances = [s.distance for s in knowledge_sources[:5] if s.distance is not None]

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.retrieve",
            data={
                "knowledge_best": knowledge_best,
                "product_best": product_best,
                "knowledge_top5_distances": knowledge_top_distances,
                "product_top5_distances": product_top_distances,
                "knowledge_count": len(knowledge_sources),
                "product_count": len(product_cards),
                "decompose_used": bool(sub_questions),
                "sub_questions_count": len(sub_questions),
                "coverage_first": True,
                "per_query_keep": per_query_keep,
            },
        )

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.merge.coverage",
            data={"kept_per_query": kept_per_query, "coverage_count": len(coverage_sources)},
        )

        # Low-confidence retrieval gate: avoid verifier producing unrelated clarifications.
        product_weak_thr = float(getattr(settings, "PRODUCT_WEAK_DISTANCE", 0.55))
        knowledge_weak_thr = float(getattr(settings, "KNOWLEDGE_WEAK_DISTANCE", 0.60))
        product_weak = (product_best is None) or (float(product_best) >= product_weak_thr)
        knowledge_weak = (knowledge_best is None) or (float(knowledge_best) >= knowledge_weak_thr)
        if product_weak and knowledge_weak:
            has_store_intent = self._has_store_intent(req.message or "")
            if has_store_intent:
                route = "fallback_general"
                reply_text = "I can help you browse products or answer store questions — what would you like to do?"
                follow_ups = ["Browse products", "Check a SKU price", "Shipping & policies"]
            else:
                route = "general_chat"
                try:
                    reply_text = await self._general_chat_response(user_text=req.message or "", history=history)
                except Exception as e:
                    logger.error(f"general_chat generation failed: {e}")
                    reply_text = "Sure — what would you like to chat about?"
                follow_ups = ["Browse products", "Check a SKU price", "Shipping & policies"]

            self._log_event(
                run_id=run_id,
                location="chat_service.route_selected",
                data={
                    "route": route,
                    "fallback_general_triggered": route == "fallback_general",
                    "reason": "weak_retrieval",
                    "product_best": product_best,
                    "knowledge_best": knowledge_best,
                    "product_weak_thr": product_weak_thr,
                    "knowledge_weak_thr": knowledge_weak_thr,
                    "verifier_skipped_reason": "weak_retrieval",
                    "store_intent": has_store_intent,
                },
            )
            await self.save_message(conversation.id, MessageRole.USER, req.message)
            await self.save_message(conversation.id, MessageRole.ASSISTANT, reply_text)
            return ChatResponse(
                conversation_id=conversation.id,
                reply_text=self._strip_sources_block(reply_text),
                product_carousel=[],
                follow_up_questions=follow_ups,
                intent=route,
                sources=[],
            )

        # Global rerank ONCE (original user question), after coverage-first merge.
        reranked_top = await self._rerank_knowledge_with_cohere(
            query=req.message,
            candidates=knowledge_sources,
            run_id=run_id,
        )

        max_verify_chunks = max(
            1, int(getattr(settings, "RAG_VERIFY_MAX_KNOWLEDGE_CHUNKS", settings.RAG_RERANK_TOPN))
        )
        used_keys: set[str] = set()
        reranked_knowledge: List[KnowledgeSource] = []
        for s in reranked_top:
            key = s.chunk_id or s.source_id
            if key in used_keys:
                continue
            reranked_knowledge.append(s)
            used_keys.add(key)
            if len(reranked_knowledge) >= max_verify_chunks:
                break
        for s in knowledge_sources:
            if len(reranked_knowledge) >= max_verify_chunks:
                break
            key = s.chunk_id or s.source_id
            if key in used_keys:
                continue
            reranked_knowledge.append(s)
            used_keys.add(key)

        decision = await self._verify_answerable(
            question=req.message,
            knowledge_sources=reranked_knowledge,
            product_cards=product_cards,
            run_id=run_id,
        )

        answerable = bool(decision.get("answerable"))
        answer_type = (decision.get("answer_type") or "knowledge").lower()
        supporting_ids = [str(x) for x in (decision.get("supporting_chunk_ids") or [])]
        missing_q = decision.get("missing_info_question")
        answerable_parts = decision.get("answerable_parts") or []
        missing_parts = decision.get("missing_parts") or []

        answerable_topics: List[str] = []
        part_supporting_ids: List[str] = []
        if isinstance(answerable_parts, list):
            for p in answerable_parts:
                if isinstance(p, dict):
                    topic = p.get("topic")
                    if isinstance(topic, str) and topic.strip():
                        answerable_topics.append(topic.strip())
                    ids = p.get("supporting_chunk_ids") or []
                    if isinstance(ids, list):
                        part_supporting_ids.extend([str(x) for x in ids])

        missing_parts_q: Optional[str] = None
        if isinstance(missing_parts, list) and missing_parts:
            first = missing_parts[0]
            if isinstance(first, dict):
                mq = first.get("missing_info_question")
                if isinstance(mq, str) and mq.strip():
                    missing_parts_q = mq.strip()

        selected_sources = reranked_knowledge
        effective_supporting_ids = part_supporting_ids or supporting_ids
        if effective_supporting_ids:
            by_id = {s.source_id: s for s in reranked_knowledge}
            selected_sources = [by_id[sid] for sid in effective_supporting_ids if sid in by_id] or reranked_knowledge

        route = "clarify"
        reply_text = ""
        sources: List[KnowledgeSource] = []
        product_carousel: List[ProductCard] = []
        follow_up_questions: List[str] = []

        if answerable:
            if answer_type == "product" and looks_like_product and product_cards:
                route = "product"
                reply_text = "Here are some products that might help:"
                product_carousel = product_cards
                sources = []
                follow_up_questions = []
            elif answer_type == "mixed":
                route = "mixed"
                reply_text = await self.synthesize_answer(req.message, selected_sources)
                product_carousel = []
                sources = selected_sources
                follow_up_questions = []
            else:
                route = "knowledge"
                reply_text = await self.synthesize_answer(req.message, selected_sources)
                product_carousel = []
                sources = selected_sources
                follow_up_questions = []
        else:
            product_weak_thr = float(getattr(settings, "PRODUCT_WEAK_DISTANCE", 0.55))
            knowledge_weak_thr = float(getattr(settings, "KNOWLEDGE_WEAK_DISTANCE", 0.60))
            product_weak = (product_best is None) or (float(product_best) >= product_weak_thr)
            knowledge_weak = (knowledge_best is None) or (float(knowledge_best) >= knowledge_weak_thr)

            if self._is_question_like(req.message) and not (product_weak and knowledge_weak):
                route = "clarify"
                clarifier = missing_parts_q or (missing_q.strip() if isinstance(missing_q, str) else "")
                if selected_sources and effective_supporting_ids and clarifier:
                    reply_text = await self.synthesize_partial_answer(
                        original_question=req.message,
                        sources=selected_sources,
                        answerable_topics=answerable_topics,
                        missing_question=clarifier,
                    )
                    sources = selected_sources
                elif clarifier:
                    reply_text = clarifier
                    sources = []
                else:
                    reply_text = "Could you clarify what exactly you want to know (one detail)?"
                    sources = []
                product_carousel = []
                follow_up_questions = []
            else:
                route = "fallback_general"
                reply_text = "I can help you browse products or answer store questions — what would you like to do?"
                product_carousel = []
                sources = []
                follow_up_questions = ["Browse products", "Check a SKU price", "Shipping & policies"]

        reply_text = self._strip_sources_block(reply_text)
        if product_carousel:
            product_carousel = currency_service.convert_product_cards(product_carousel, to_currency=target_currency)

        if route not in {"smalltalk", "product"}:
            reply_text = await answer_polisher.polish(
                draft_text=reply_text,
                route=route,
                user_text=req.message,
                has_product_carousel=bool(product_carousel),
            )
            reply_text = self._strip_sources_block(reply_text)

        self._log_event(
            run_id=run_id,
            location="chat_service.rag.route_decision",
            data={
                "route": route,
                "answerable": answerable,
                "answer_type": answer_type,
                "knowledge_best": knowledge_best,
                "product_best": product_best,
                "knowledge_threshold_observed": settings.KNOWLEDGE_DISTANCE_THRESHOLD,
                "product_threshold_observed": settings.PRODUCT_DISTANCE_THRESHOLD,
                "selected_source_ids": [s.source_id for s in sources[:5]],
                "product_carousel_count": len(product_carousel),
            },
        )

        logger.info(
            "chat_route decision",
            extra={
                "knowledge_best_distance": knowledge_best,
                "product_best_distance": product_best,
                "route": route,
            },
        )

        # persist messages
        await self.save_message(conversation.id, MessageRole.USER, req.message)
        await self.save_message(conversation.id, MessageRole.ASSISTANT, reply_text)

        return ChatResponse(
            conversation_id=conversation.id,
            reply_text=reply_text,
            product_carousel=product_carousel,
            follow_up_questions=follow_up_questions,
            intent=route,
            sources=sources,
        )
