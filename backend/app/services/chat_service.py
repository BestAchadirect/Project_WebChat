from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.config import settings
from app.models.chat import AppUser, Conversation, Message, MessageRole
from app.models.product import Product, ProductEmbedding
from app.prompts.system_prompts import (
    rag_answer_prompt,
    ui_localization_prompt,
    unified_nlu_prompt,
)
from app.schemas.chat import ChatContext, ChatRequest, ChatResponse, KnowledgeSource, ProductCard, RouteDecision
from app.services.llm_service import llm_service
from app.services.product_pipeline import ProductPipeline
from app.services.knowledge_pipeline import KnowledgePipeline
from app.services.verifier_service import VerifierService
from app.services.currency_service import currency_service
from app.services.response_renderer import ResponseRenderer
from app.services.semantic_cache_service import semantic_cache_service
from app.utils.debug_log import debug_log as _debug_log

logger = get_logger(__name__)


class ChatService:
    """Chat orchestration (intent -> retrieval -> response)."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._product_pipeline = ProductPipeline(
            search_products=self.search_products,
            search_products_by_exact_sku=self._search_products_by_exact_sku,
            infer_jewelry_type_filter=self._infer_jewelry_type_filter,
            log_event=self._log_event,
        )
        self._knowledge_pipeline = KnowledgePipeline(db=self.db, log_event=self._log_event)
        self._verifier_service = VerifierService(log_event=self._log_event)
        self._response_renderer = ResponseRenderer()





    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        lowered = text.lower()
        lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered).strip()
        return lowered



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

    async def _run_nlu(self, *, user_text: str, history: List[Dict[str, str]] = None, locale: Optional[str], run_id: str) -> Dict[str, Any]:
        """Run unified NLU for language, intent, and currency."""
        if not user_text or len(user_text.strip()) < 3:
            return {
                "language": "English",
                "locale": "en-US",
                "intent": "knowledge_query",
                "show_products": False,
                "currency": "",
            }

        supported = currency_service.supported_currencies()
        data = await llm_service.run_nlu(
            user_message=user_text,
            history=history,
            locale=locale,
            supported_currencies=supported,
            model=getattr(settings, "NLU_MODEL", None),
            max_tokens=int(getattr(settings, "NLU_MAX_TOKENS", 250)),
        )

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

    async def _get_product_category_overview(self, limit: int = 6) -> List[str]:
        stmt = (
            select(Product.jewelry_type, func.count(Product.id))
            .where(Product.is_active.is_(True))
            .where(Product.jewelry_type.isnot(None))
            .group_by(Product.jewelry_type)
            .order_by(func.count(Product.id).desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        categories: List[str] = []
        for name, _count in rows:
            if name:
                categories.append(str(name).strip())
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

    async def _finalize_response(
        self,
        *,
        conversation_id: int,
        user_text: str,
        response: ChatResponse,
    ) -> ChatResponse:
        await self.save_message(conversation_id, MessageRole.USER, user_text)
        await self.save_message(conversation_id, MessageRole.ASSISTANT, response.reply_text)
        return response

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

        context = "\n\n".join(
            [
                f"ID: {s.source_id}\nTITLE: {s.title}\nTEXT: {s.content_snippet}"
                for s in sources[: min(5, len(sources))]
            ]
        )
        messages = [
            {
                "role": "system",
                "content": rag_answer_prompt(reply_language),
            },
        ]
        
        # Insert last 5 messages for context
        if history:
            messages.extend(history)
            
        messages.append({"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"})
        try:
            data = await llm_service.generate_chat_json(messages, temperature=0.2)
            return {
                "reply": str(data.get("reply", "")),
                "carousel_hint": str(data.get("carousel_hint", "")),
            }
        except Exception as e:
            logger.error(f"LLM response generation failed: {e}")
            msg = await self._localize_ui_text(
                reply_language=reply_language,
                text="I'm having trouble generating an answer right now. Please try again.",
                run_id=run_id or "synthesize_answer",
            )
            return {"reply": msg, "carousel_hint": ""}


    async def process_chat(self, req: ChatRequest) -> ChatResponse:
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        
        run_id = f"chat-{int(time.time() * 1000)}"
        debug_meta: Dict[str, Any] = {
            "run_id": run_id,
            "route": "rag_strict"
        }

        # 1. Unified NLU Analysis
        text = req.message or ""
        
        # Fetch last 5 messages for context memory
        history = []
        if conversation.id:
            history = await self.get_history(conversation.id, limit=5)
            
        nlu_data = await self._run_nlu(user_text=text, history=history, locale=req.locale, run_id=run_id)
        debug_meta["nlu"] = nlu_data

        reply_language = await self._resolve_reply_language(
            nlu_data=nlu_data, 
            user_text=text, 
            locale=req.locale, 
            run_id=run_id
        )
        debug_meta["reply_language"] = reply_language

        default_display_currency = (
            getattr(settings, "PRICE_DISPLAY_CURRENCY", None)
            or getattr(settings, "BASE_CURRENCY", None)
            or "USD"
        )
        target_currency = await self._resolve_target_currency(nlu_data=nlu_data, user_text=text)
        debug_meta["target_currency"] = target_currency

        # 2. Universal Retrieval (Always Search)
        # Use refined query for search if available, otherwise fallback to original text
        search_query = nlu_data.get("refined_query") or text
        
        # 2a. Product Search
        ctx = ChatContext(
            text=text,
            is_question_like=True,
            looks_like_product=False,
            has_store_intent=False,
            is_policy_intent=False,
            policy_topic_count=0,
            sku_token=None,
            requested_currency=target_currency if target_currency != default_display_currency.upper() else None,
        )
        query_embedding = await llm_service.generate_embedding(search_query)
        
        product_cards, distances, best_distance, dist_map = await self.search_products(
            query_embedding=query_embedding,
            limit=5,
            run_id=run_id
        )
        
        # 2b. Knowledge Search
        kb_sources, _ = await self._knowledge_pipeline.search_knowledge(
            query_text=search_query,
            query_embedding=query_embedding,
            limit=5,
            run_id=run_id
        )

        sources: List[KnowledgeSource] = []
        
        # 3. Intent Logic (Using NLU results)
        intent = str(nlu_data.get("intent") or "knowledge_query").strip().lower()
        show_products_flag = bool(nlu_data.get("show_products", False))
        
        # 4. Filter Products based on intent and relevance
        top_products = []
        product_threshold = getattr(settings, "PRODUCT_DISTANCE_THRESHOLD", 0.45)

        # Relax threshold if NLU says user wants to see products
        if show_products_flag:
            if intent == "browse_products":
                product_threshold = 0.85  # Very relaxed for browsing
            else:
                product_threshold = 0.65  # Moderately relaxed for specific search

        if product_cards and best_distance is not None and best_distance < product_threshold:
            top_products = product_cards
            # Create a source snippet for products
            product_text = "\n".join([f"TYPE: {p.attributes.get('jewelry_type', 'Jewelry')}, NAME: {p.name}, SKU: {p.sku}, PRICE: {p.price} {p.currency}" for p in top_products[:3]])
            sources.append(KnowledgeSource(
                source_id="product_listings",
                title="Current Store Products",
                content_snippet=f"The following products are available in the store:\n{product_text}",
                relevance=1.0 - best_distance,
            ))
        elif show_products_flag and product_cards:
            # Fallback: Always show some products if user wants products, even if below threshold
            top_products = product_cards[:3]
            product_text = "\n".join([f"- {p.attributes.get('jewelry_type', 'Jewelry')} {p.name} ({p.sku}): {p.price} {p.currency}" for p in top_products])
            sources.append(KnowledgeSource(
                source_id="products_fallback",
                title="Related Products",
                content_snippet=f"Here are some products you might be interested in:\n{product_text}",
                relevance=0.3,  # Low relevance indicator
            ))
            debug_meta["product_fallback_used"] = True

        sources.extend(kb_sources)

        # 4. Generate Response (Strict RAG)
        reply_data = await self.synthesize_answer(
            question=text,
            sources=sources,
            reply_language=reply_language,
            history=history,
            run_id=run_id
        )

        # 5. Render
        response = await self._response_renderer.render(
            conversation_id=conversation.id,
            route="rag_strict",
            reply_data=reply_data,
            product_carousel=top_products,
            follow_up_questions=[], # Removed as requested
            sources=sources,
            debug=debug_meta,
            reply_language=reply_language,
            target_currency=target_currency,
            user_text=text,
            apply_polish=False,
        )

        return await self._finalize_response(
            conversation_id=conversation.id,
            user_text=text,
            response=response,
        )


