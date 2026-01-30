from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.config import settings
from app.models.chat import AppUser, Conversation, Message, MessageRole
from app.models.product import Product, ProductEmbedding
from app.models.qa_log import QALog, QAStatus
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
    def _normalize_jewelry_type(value: Optional[str]) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", "", value.lower())

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

    @staticmethod
    def _clean_code_candidate(token: str) -> str:
        return (token or "").strip(".,!?;:'\"()[]{}<>")

    @staticmethod
    def _looks_like_code(token: str) -> bool:
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
        is_all_upper = t.isupper()
        return has_digit or has_sep or (is_all_upper and len(t) <= 10)

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

    @staticmethod
    def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if not dt:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

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
                now = datetime.now(timezone.utc)
                started_at = self._ensure_utc(existing.started_at)
                last_message_at = self._ensure_utc(existing.last_message_at) or started_at

                idle_minutes = int(getattr(settings, "CONVERSATION_IDLE_TIMEOUT_MINUTES", 30) or 0)
                hard_cap_hours = int(getattr(settings, "CONVERSATION_HARD_CAP_HOURS", 24) or 0)

                idle_expired = False
                hard_cap_expired = False

                if idle_minutes > 0 and last_message_at:
                    idle_expired = last_message_at < (now - timedelta(minutes=idle_minutes))
                if hard_cap_hours > 0 and started_at:
                    hard_cap_expired = started_at < (now - timedelta(hours=hard_cap_hours))

                if not (idle_expired or hard_cap_expired):
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
                {"source_id": s.source_id, "title": s.title, "relevance": s.relevance}
                for s in response.sources
            ],
            status=qa_status,
            token_usage=token_usage,
            channel=channel,
        )

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
            except Exception as e:
                logger.error(f"Failed to log QA event: {e}")

            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return response

    async def get_history(self, conversation_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        msgs = result.scalars().all()
        return [
            {
                "role": m.role, 
                "content": m.content,
                "product_data": m.product_data
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
        """
        Smart search with prioritization:
        1. Exact SKU match -> Return specific variant
        2. Master Code / Name match -> Return all variants in group
        3. Vector Search -> Fallback
        """
        candidates = self._extract_code_candidates(query=query, extracted_code=extracted_code)
        if not candidates:
            return await self.search_products(query_embedding, limit, run_id)
        
        for candidate in candidates:
            clean_cand = candidate
            if not clean_cand or not self._looks_like_code(clean_cand):
                continue

            # 1. Exact SKU Match
            sku_stmt = select(Product).where(Product.sku.ilike(clean_cand))
            sku_result = await self.db.execute(sku_stmt)
            sku_product = sku_result.scalars().first()
            
            if sku_product:
                logger.info(f"Smart Search: Found exact SKU match for '{clean_cand}'")
                card = self._product_to_card(sku_product)
                return [card], [0.0], 0.0, {str(sku_product.id): 0.0}
                
            # 2. Exact Master Code / Product Name Match
            master_stmt = select(Product).where(or_(
                Product.master_code.ilike(clean_cand),
                Product.name.ilike(clean_cand)
            )).limit(1)
            master_result = await self.db.execute(master_stmt)
            master_product = master_result.scalars().first()
            
            if master_product:
                logger.info(f"Smart Search: Found master code match for '{clean_cand}' (Group: {master_product.group_id})")
                # Fetch all variants in this group
                variants_stmt = select(Product).where(Product.group_id == master_product.group_id)
                variants_result = await self.db.execute(variants_stmt)
                variants = variants_result.scalars().all()
                
                cards = [self._product_to_card(p) for p in variants]
                if len(cards) > limit * 2:
                    cards = cards[:limit * 2]
                    
                distances = [0.0] * len(cards)
                dist_map = {str(c.id): 0.0 for c in cards}
                return cards, distances, 0.0, dist_map
            
        # 3. Fallback to Vector Search
        return await self.search_products(query_embedding, limit, run_id)

    def _product_to_card(self, product: Product) -> ProductCard:
        attrs = dict(product.attributes or {})
        if product.jewelry_type and "jewelry_type" not in attrs:
            attrs["jewelry_type"] = product.jewelry_type
        if product.material and "material" not in attrs:
            attrs["material"] = product.material
        if product.gauge and "gauge" not in attrs:
            attrs["gauge"] = product.gauge
        if product.threading and "threading" not in attrs:
            attrs["threading"] = product.threading
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


    async def process_chat(self, req: ChatRequest, channel: Optional[str] = None) -> ChatResponse:
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        
        run_id = f"chat-{int(time.time() * 1000)}"
        channel = channel or "widget"
        debug_meta: Dict[str, Any] = {
            "run_id": run_id,
            "route": "rag_strict",
            "channel": channel,
        }
        llm_service.begin_token_tracking()

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

        # 2. Retrieval Gating (Skip unnecessary searches)
        # Use refined query for search if available, otherwise fallback to original text
        search_query = nlu_data.get("refined_query") or text

        intent = str(nlu_data.get("intent") or "knowledge_query").strip().lower()
        show_products_flag = bool(nlu_data.get("show_products", False))
        nlu_product_code = str(nlu_data.get("product_code") or "").strip()
        nlu_product_code = self._clean_code_candidate(nlu_product_code)

        sku_token = self._extract_sku(text)
        if nlu_product_code and self._looks_like_code(nlu_product_code):
            sku_token = sku_token or nlu_product_code

        is_product_intent = intent in {"browse_products", "search_specific"} or show_products_flag
        if sku_token:
            is_product_intent = True

        if intent in {"knowledge_query", "off_topic"}:
            use_knowledge = True
            use_products = show_products_flag or bool(sku_token)
        elif intent in {"browse_products", "search_specific"}:
            use_products = True
            use_knowledge = False
        else:
            use_products = False
            use_knowledge = False

        is_question_like = self._is_question_like(text)
        is_complex = self._is_complex_query(text)
        policy_topic_count = self._count_policy_topics(text)
        is_policy_intent = intent == "knowledge_query" and policy_topic_count > 0

        looks_like_product = bool(self._infer_jewelry_type_filter(text) or sku_token or is_product_intent)
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
        debug_meta["retrieval_gate"] = {
            "use_products": use_products,
            "use_knowledge": use_knowledge,
            "is_complex": is_complex,
            "is_policy_intent": is_policy_intent,
            "policy_topic_count": policy_topic_count,
        }

        query_embedding: Optional[List[float]] = None
        if use_products or use_knowledge:
            query_embedding = await llm_service.generate_embedding(search_query)

        product_cards: List[ProductCard] = []
        distances: List[float] = []
        best_distance: Optional[float] = None
        dist_map: Dict[str, float] = {}
        if use_products and query_embedding is not None:
            product_cards, distances, best_distance, dist_map = await self.smart_product_search(
                query=search_query,
                query_embedding=query_embedding,
                limit=10,
                run_id=run_id,
                extracted_code=nlu_product_code,
            )

        kb_sources: List[KnowledgeSource] = []
        if use_knowledge and query_embedding is not None:
            if is_policy_intent or is_complex:
                max_sub_questions = int(getattr(settings, "RAG_DECOMPOSE_MAX_SUBQUESTIONS", 5))
                knowledge_result = await self._knowledge_pipeline.retrieve(
                    ctx=ctx,
                    knowledge_query_text=search_query,
                    knowledge_embedding=query_embedding,
                    is_complex=is_complex,
                    is_question_like=is_question_like,
                    is_policy_intent=is_policy_intent,
                    policy_topic_count=policy_topic_count,
                    max_sub_questions=max_sub_questions,
                    run_id=run_id,
                )
                kb_sources = knowledge_result.knowledge_sources
                debug_meta["knowledge_decompose_used"] = knowledge_result.decomposition_used
                debug_meta["knowledge_decompose_reason"] = knowledge_result.decomposition_reason
            else:
                kb_sources, _ = await self._knowledge_pipeline.search_knowledge(
                    query_text=search_query,
                    query_embedding=query_embedding,
                    limit=5,
                    run_id=run_id,
                )

        sources: List[KnowledgeSource] = []
        
        # 3. Intent Logic (Using NLU results)
        
        # Override show_products_flag if we found an EXACT match (smart search)
        if best_distance is not None and best_distance == 0.0 and product_cards:
            logger.info("Forcing show_products=True due to exact SKU/MasterCode match")
            show_products_flag = True
            intent = "search_specific"

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
            top_products = product_cards[:10]  # Show up to 10 products
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
            top_products = product_cards[:10]  # Show up to 10 products
            product_text = "\n".join([f"- {p.attributes.get('jewelry_type', 'Jewelry')} {p.name} ({p.sku}): {p.price} {p.currency}" for p in top_products])
            sources.append(KnowledgeSource(
                source_id="products_fallback",
                title="Related Products",
                content_snippet=f"Here are some products you might be interested in:\n{product_text}",
                relevance=0.3,  # Low relevance indicator
            ))
            debug_meta["product_fallback_used"] = True

        # 4b. Cross-sell accessories (e.g., barbell attachments)
        cross_sell_products: List[ProductCard] = []
        cross_sell_label: Optional[str] = None
        cross_sell_used = False
        if top_products:
            primary_type = self._infer_primary_jewelry_type(products=top_products, query_text=search_query)
            cross_sell_query = self._build_cross_sell_query(primary_type or "")
            cross_sell_label = self._build_cross_sell_label(primary_type or "")
            if cross_sell_query:
                cross_embedding = await llm_service.generate_embedding(cross_sell_query)
                cross_cards, _cross_distances, _cross_best, _cross_map = await self.search_products(
                    cross_embedding,
                    limit=12,
                    run_id=run_id,
                )
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

        sources.extend(kb_sources)

        max_answer_sources = int(getattr(settings, "RAG_MAX_SOURCES_IN_RESPONSE", 5))
        sources_for_answer = sources[:max_answer_sources]
        debug_meta["retrieved_source_count"] = len(sources)
        debug_meta["answer_source_count"] = len(sources_for_answer)

        # 4. Generate Response (Strict RAG)
        reply_data = await self.synthesize_answer(
            question=text,
            sources=sources_for_answer,
            reply_language=reply_language,
            history=history,
            run_id=run_id
        )

        # 5. Render
        # Add "See more" button if products are shown
        follow_up_questions = []
        
        # Priority 1: Context-aware questions from LLM
        if reply_data.get("recommended_questions"):
            follow_up_questions = reply_data["recommended_questions"]
            
        # Priority 2: Smart fallback IF no LLM suggestions and products exist
        elif top_products:
            # Extract the primary search term for "See more" query
            jewelry_type = top_products[0].attributes.get('jewelry_type', '')
            material = top_products[0].attributes.get('material', '')
            search_term = jewelry_type or material or "similar items"
            follow_up_questions = [f"See more {search_term}"]

        if cross_sell_used and cross_sell_label:
            accessory_question = f"Show {cross_sell_label}"
            if accessory_question not in follow_up_questions:
                follow_up_questions.append(accessory_question)
            
        # Enforce limit of 5
        if len(follow_up_questions) > 5:
            follow_up_questions = follow_up_questions[:5]
        
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

        token_usage = llm_service.consume_token_usage()
        return await self._finalize_response(
            conversation_id=conversation.id,
            user_text=text,
            response=response,
            token_usage=token_usage,
            channel=channel,
        )


