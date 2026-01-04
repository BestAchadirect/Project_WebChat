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
    contextual_reply_prompt,
    general_chat_prompt,
    language_detect_prompt,
    rag_answer_prompt,
    rag_partial_prompt,
    smalltalk_prompt,
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

    def _policy_topic_count(self, text: str) -> int:
        if not text:
            return 0
        lowered = text.strip().lower()
        if not lowered:
            return 0
        topics = [
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
            "credit",
            "store credit",
        ]
        return sum(1 for t in topics if t in lowered)

    def _is_complex_query(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip()
        if not t:
            return False
        if len(t) > 220:
            return True
        if t.count("?") >= 2:
            return True
        if "\n" in t or re.search(r"(^|\n)\s*[-*]\s+\w+", t):
            return True
        if self._policy_topic_count(t) >= 2:
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
        return self._policy_topic_count(text) > 0

    def _is_catalog_browse(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        patterns = [
            r"\bwhat products do you have\b",
            r"\bwhat do you sell\b",
            r"\bwhat do you carry\b",
            r"\bproduct catalog\b",
            r"\bbrowse (the )?catalog\b",
            r"\bshow me (the )?products\b",
            r"\bproduct categories\b",
            r"\bwhat categories\b",
        ]
        return any(re.search(p, t) for p in patterns)

    def _build_product_clarifier(self, text: str) -> str:
        t = (text or "").lower()
        if not re.search(
            r"\b(barbell|labret|belly|nose|ring|stud|tunnel|plug|nipple|jewelry|earring|septum|industrial)\b",
            t,
        ):
            return "Which category are you interested in (barbells, labrets, belly, or nose)?"
        if not re.search(r"\b\d{1,2}g\b", t):
            return "What gauge are you looking for (14g or 16g)?"
        if not re.search(r"\b(titanium|steel|gold|silver|niobium)\b", t):
            return "Any material preference (titanium or steel)?"
        return "Do you have a size or style in mind?"

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        lowered = text.lower()
        lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered).strip()
        return lowered

    def _is_echo_clarifier(self, *, user_text: str, clarifier: str) -> bool:
        if not user_text or not clarifier:
            return False
        u = self._normalize_text(user_text)
        c = self._normalize_text(clarifier)
        if not u or not c:
            return False
        if c in u or u in c:
            return True
        return False


    @staticmethod
    def _count_sentences(text: str) -> int:
        if not text:
            return 0
        parts = re.split(r"[.!?]+", text)
        return len([p for p in parts if p.strip()])

    def _format_clarifier_fallback(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            t = "Could you share a bit more detail so I can help?"
        t = re.sub(r"\s+", " ", t)
        if "?" not in t:
            t = t.rstrip(".")
            t = f"{t}?"
        if not re.match(r"^(hello|thanks)\b", t, re.I):
            if t and len(t) > 1 and t[0].isupper() and t[1].islower():
                t = t[0].lower() + t[1:]
            t = f"Hello, {t}"
        return t

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

    async def _generate_contextual_reply(
        self,
        *,
        user_text: str,
        reply_language: str,
        suggested_question: str,
        focus: str,
        run_id: str,
        required_terms: Optional[List[str]] = None,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> str:
        fallback = self._format_clarifier_fallback(suggested_question)
        fallback = await self._localize_ui_text(
            reply_language=reply_language,
            text=fallback,
            run_id=run_id,
        )

        def _set_telemetry(used: bool, reason: str) -> None:
            if telemetry is None:
                return
            telemetry["contextual_reply_used"] = used
            telemetry["contextual_reply_reason"] = reason
            telemetry["contextual_reply_focus"] = focus

        if not bool(getattr(settings, "CONTEXTUAL_REPLY_ENABLED", True)):
            _set_telemetry(False, "disabled")
            return fallback
        system_prompt = contextual_reply_prompt(reply_language)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"User message: {user_text}\n"
                    f"Focus: {focus}\n"
                    f"Suggested question: {suggested_question}"
                ),
            },
        ]
        model = getattr(settings, "CONTEXTUAL_REPLY_MODEL", None) or settings.OPENAI_MODEL
        max_tokens = int(getattr(settings, "CONTEXTUAL_REPLY_MAX_TOKENS", 120))
        temperature = float(getattr(settings, "CONTEXTUAL_REPLY_TEMPERATURE", 0.3))
        try:
            reply = await llm_service.generate_chat_response(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
            )
        except Exception as e:
            self._log_event(
                run_id=run_id,
                location="chat_service.reply.contextual",
                data={"used": False, "reason": "llm_error", "error": str(e), "focus": focus},
            )
            _set_telemetry(False, "llm_error")
            return fallback

        reply = re.sub(r"\s+", " ", (reply or "").strip())
        if not reply:
            self._log_event(
                run_id=run_id,
                location="chat_service.reply.contextual",
                data={"used": False, "reason": "empty_response", "focus": focus},
            )
            _set_telemetry(False, "empty_response")
            return fallback
        if not re.match(r"^(hello|thanks)\b", reply, re.I):
            self._log_event(
                run_id=run_id,
                location="chat_service.reply.contextual",
                data={"used": False, "reason": "missing_greeting", "focus": focus},
            )
            _set_telemetry(False, "missing_greeting")
            return fallback
        if "?" not in reply:
            self._log_event(
                run_id=run_id,
                location="chat_service.reply.contextual",
                data={"used": False, "reason": "missing_question", "focus": focus},
            )
            _set_telemetry(False, "missing_question")
            return fallback
        if self._count_sentences(reply) > 2:
            self._log_event(
                run_id=run_id,
                location="chat_service.reply.contextual",
                data={"used": False, "reason": "too_long", "focus": focus},
            )
            _set_telemetry(False, "too_long")
            return fallback
        if required_terms:
            lower_reply = reply.lower()
            missing_terms = [t for t in required_terms if t.lower() not in lower_reply]
            if missing_terms:
                self._log_event(
                    run_id=run_id,
                    location="chat_service.reply.contextual",
                    data={
                        "used": False,
                        "reason": "missing_terms",
                        "focus": focus,
                        "missing_terms": missing_terms,
                    },
                )
                _set_telemetry(False, "missing_terms")
                return fallback

        self._log_event(
            run_id=run_id,
            location="chat_service.reply.contextual",
            data={"used": True, "reason": "accepted", "focus": focus},
        )
        _set_telemetry(True, "accepted")
        return reply

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

    async def _detect_language(self, *, user_text: str, run_id: str) -> Dict[str, str]:
        if not user_text or len(user_text.strip()) < 3:
            return {}
        system = language_detect_prompt()
        model = getattr(settings, "LANGUAGE_DETECT_MODEL", None) or settings.OPENAI_MODEL
        max_tokens = int(getattr(settings, "LANGUAGE_DETECT_MAX_TOKENS", 40))
        try:
            data = await llm_service.generate_chat_json(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
                model=model,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        except Exception as e:
            self._log_event(
                run_id=run_id,
                location="chat_service.language.detect",
                data={"error": str(e)},
            )
            return {}

        language = str(data.get("language") or "").strip()
        locale = str(data.get("locale") or "").strip()
        if language.lower() in {"unknown", "none"}:
            language = ""
        if locale.lower() in {"unknown", "none"}:
            locale = ""

        self._log_event(
            run_id=run_id,
            location="chat_service.language.detect",
            data={"language": language, "locale": locale},
        )
        return {"language": language, "locale": locale}

    async def _resolve_reply_language(self, *, user_text: str, locale: Optional[str], run_id: str) -> str:
        mode = str(getattr(settings, "CHAT_LANGUAGE_MODE", "auto") or "auto").lower()
        default_locale = str(getattr(settings, "DEFAULT_LOCALE", "en-US") or "en-US")
        locale = str(locale or "").strip() or None
        if mode == "fixed":
            fixed = str(getattr(settings, "FIXED_REPLY_LANGUAGE", "") or "").strip()
            reply_language = fixed or default_locale
            reason = "fixed"
            self._log_event(
                run_id=run_id,
                location="chat_service.language.resolve",
                data={"mode": mode, "reply_language": reply_language, "reason": reason},
            )
            return reply_language
        if mode == "locale":
            reply_language = locale or default_locale
            reason = "locale"
            self._log_event(
                run_id=run_id,
                location="chat_service.language.resolve",
                data={"mode": mode, "reply_language": reply_language, "reason": reason},
            )
            return reply_language

        # auto: treat locale as a hint, not a hard override.
        # Many clients always send a default like "en-US", which would otherwise prevent detection.
        if locale and locale.lower() != default_locale.lower():
            reply_language = locale
            reason = "locale_override"
            self._log_event(
                run_id=run_id,
                location="chat_service.language.resolve",
                data={"mode": mode, "reply_language": reply_language, "reason": reason},
            )
            return reply_language

        trimmed = (user_text or "").strip()
        if trimmed and trimmed.isascii() and len(trimmed) <= 6:
            reply_language = locale or default_locale
            reason = "short_ascii"
            self._log_event(
                run_id=run_id,
                location="chat_service.language.resolve",
                data={"mode": mode, "reply_language": reply_language, "reason": reason},
            )
            return reply_language

        detected = await self._detect_language(user_text=user_text, run_id=run_id)
        reply_language = self._format_language_instruction(
            language=detected.get("language"),
            locale=detected.get("locale"),
        )
        if detected:
            reason = "detected"
        else:
            reply_language = locale or default_locale
            reason = "fallback_default"
        self._log_event(
            run_id=run_id,
            location="chat_service.language.resolve",
            data={"mode": mode, "reply_language": reply_language, "reason": reason},
        )
        return reply_language

    async def _detect_requested_currency(
        self,
        *,
        text: str,
        locale: Optional[str],
        run_id: str,
    ) -> tuple[Optional[str], Dict[str, Any]]:
        meta = {
            "currency_intent_used": False,
            "currency_intent_source": "heuristic",
            "currency_intent_intent": None,
            "currency_intent_currency": None,
        }

        if not (text or "").strip():
            meta["currency_intent_source"] = "empty"
            return None, meta

        lowered = text.lower()
        has_digits = bool(re.search(r"\d", lowered))
        has_symbols = bool(re.search(r"[$\u20AC\u00A3\u00A5\u0E3F]", text))
        has_currency_word = bool(
            re.search(
                r"\b(usd|thb|eur|gbp|jpy|cny|rmb|aud|cad|sgd|hkd|myr|idr|vnd|php|krw|inr|"
                r"dollar|dollars|euro|euros|pound|pounds|yen|baht|rupee|rupees)\b",
                lowered,
            )
        )
        if not (has_digits or has_symbols or has_currency_word):
            meta["currency_intent_source"] = "heuristic_skip"
            return None, meta

        use_llm = bool(getattr(settings, "CURRENCY_INTENT_ENABLED", True))
        if use_llm:
            meta["currency_intent_used"] = True
            meta["currency_intent_source"] = "llm"
            supported = currency_service.supported_currencies()
            try:
                data = await llm_service.detect_currency_intent(
                    user_message=text,
                    locale=locale,
                    supported_currencies=supported,
                    model=getattr(settings, "CURRENCY_INTENT_MODEL", None),
                    max_tokens=int(getattr(settings, "CURRENCY_INTENT_MAX_TOKENS", 80)),
                )
            except Exception as e:
                self._log_event(
                    run_id=run_id,
                    location="chat_service.currency.intent",
                    data={"used": True, "error": str(e)},
                )
                data = {}

            if data:
                intent_value = data.get("intent")
                if isinstance(intent_value, bool):
                    meta["currency_intent_intent"] = intent_value
                currency_value = str(data.get("currency") or "").strip().upper()
                if currency_value:
                    meta["currency_intent_currency"] = currency_value
                self._log_event(
                    run_id=run_id,
                    location="chat_service.currency.intent",
                    data={"used": True, "intent": meta["currency_intent_intent"], "currency": currency_value},
                )

                if meta["currency_intent_intent"] is False:
                    return None, meta

                if currency_value:
                    if currency_service.supports(currency_value):
                        return currency_value, meta
                    self._log_event(
                        run_id=run_id,
                        location="chat_service.currency.intent",
                        data={"used": True, "unsupported_currency": currency_value},
                    )

            meta["currency_intent_source"] = "heuristic_fallback"

        heuristic = currency_service.extract_requested_currency(text)
        if heuristic and currency_service.supports(heuristic):
            meta["currency_intent_currency"] = heuristic
            return heuristic, meta

        return None, meta

    async def _plan_retrieval(self, *, user_text: str, locale: Optional[str], run_id: str) -> Dict[str, Any]:
        if not bool(getattr(settings, "PLANNER_ENABLED", True)):
            return {"used": False, "reason": "disabled"}

        try:
            data = await llm_service.plan_retrieval(
                user_message=user_text,
                locale=locale,
                model=getattr(settings, "PLANNER_MODEL", None),
                max_tokens=int(getattr(settings, "PLANNER_MAX_TOKENS", 200)),
            )
        except Exception as e:
            self._log_event(
                run_id=run_id,
                location="chat_service.planner",
                data={"used": True, "error": str(e)},
            )
            return {"used": True, "error": str(e), "task": "general", "confidence": 0.0}

        task = str(data.get("task") or "").strip().lower()
        allowed_tasks = {"product_search", "shipping_region", "policy", "contact", "general", "mixed"}
        if task not in allowed_tasks:
            task = "general"

        def _safe_str(value: Any) -> str:
            if not isinstance(value, str):
                return ""
            return value.strip()

        try:
            confidence = float(data.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0

        result = {
            "used": True,
            "task": task,
            "is_smalltalk": bool(data.get("is_smalltalk")),
            "is_meta_question": bool(data.get("is_meta_question")),
            "is_catalog_browse": bool(data.get("is_catalog_browse")),
            "kb_query": _safe_str(data.get("kb_query")),
            "product_query": _safe_str(data.get("product_query")),
            "entities": data.get("entities") if isinstance(data.get("entities"), dict) else {},
            "needs_clarification": bool(data.get("needs_clarification")),
            "clarifying_question": _safe_str(data.get("clarifying_question")),
            "confidence": confidence,
        }
        self._log_event(
            run_id=run_id,
            location="chat_service.planner",
            data=result,
        )
        return result

    async def _general_chat_response(
        self,
        *,
        user_text: str,
        reply_language: str,
        history: List[Dict[str, str]],
    ) -> str:
        model = getattr(settings, "GENERAL_CHAT_MODEL", None) or settings.OPENAI_MODEL
        max_tokens = int(getattr(settings, "GENERAL_CHAT_MAX_TOKENS", 250))
        system = general_chat_prompt(reply_language)
        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
        for m in history[-6:]:
            role = m.get("role")
            content = m.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        return await llm_service.generate_chat_response(messages, temperature=0.5, max_tokens=max_tokens, model=model)

    async def _smalltalk_response(self, *, user_text: str, reply_language: str) -> str:
        mode = str(getattr(settings, "SMALLTALK_MODE", "static") or "static").lower()
        lang = (reply_language or "").strip().lower()
        is_english = lang.startswith("en") or "english" in lang
        if mode != "llm" and is_english:
            return "Hello, thank you for reaching out. How may I assist you today?"

        model = getattr(settings, "SMALLTALK_MODEL", None) or settings.OPENAI_MODEL
        system = smalltalk_prompt(reply_language)
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
        run_id: Optional[str] = None,
    ) -> str:
        if not sources:
            return await self._localize_ui_text(
                reply_language=reply_language,
                text=(
                    "I don't have enough information in my knowledge base to answer that yet. "
                    "Try asking another question or rephrasing."
                ),
                run_id=run_id or "synthesize_answer",
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
                "content": rag_answer_prompt(reply_language),
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ]
        try:
            return await llm_service.generate_chat_response(messages, temperature=0.2)
        except Exception as e:
            logger.error(f"LLM response generation failed: {e}")
            return await self._localize_ui_text(
                reply_language=reply_language,
                text="I'm having trouble generating an answer right now. Please try again.",
                run_id=run_id or "synthesize_answer",
            )

    async def synthesize_partial_answer(
        self,
        *,
        original_question: str,
        sources: List[KnowledgeSource],
        answerable_topics: List[str],
        missing_question: str,
        reply_language: str,
        run_id: Optional[str] = None,
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
                "content": rag_partial_prompt(reply_language),
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
            found = await self._localize_ui_text(
                reply_language=reply_language,
                text="What I found:\n- I couldn't generate a summary from the retrieved context.",
                run_id=run_id or "synthesize_partial_answer",
            )

        confirm_label = await self._localize_ui_text(
            reply_language=reply_language,
            text="One question to confirm:",
            run_id=run_id or "synthesize_partial_answer",
        )
        return f"{found}\n\n{confirm_label}\n{missing_question}"

    async def process_chat(self, req: ChatRequest) -> ChatResponse:
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        history = await self.get_history(conversation.id)

        run_id = f"chat-{int(time.time() * 1000)}"
        debug_meta: Dict[str, Any] = {
            "run_id": run_id,
            "decomposition_used": False,
            "decomposition_reason": "not_evaluated",
            "rerank_used": False,
            "rerank_reason": "not_evaluated",
            "rerank_duration_ms": 0,
            "rerank_timed_out": False,
            "reply_language": None,
            "contextual_reply_used": None,
            "contextual_reply_reason": None,
            "contextual_reply_focus": None,
            "currency_intent_used": None,
            "currency_intent_source": None,
            "currency_intent_intent": None,
            "currency_intent_currency": None,
        }

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
        requested_currency, currency_meta = await self._detect_requested_currency(
            text=text,
            locale=req.locale,
            run_id=run_id,
        )
        debug_meta.update(currency_meta)
        default_display_currency = (
            getattr(settings, "PRICE_DISPLAY_CURRENCY", None)
            or getattr(settings, "BASE_CURRENCY", None)
            or "USD"
        )
        default_display_currency = str(default_display_currency).upper()
        if requested_currency and not currency_service.supports(requested_currency):
            requested_currency = None

        ctx = ChatContext.from_request(
            text=text,
            is_question_like=self._is_question_like(text),
            looks_like_product=self._looks_like_product_query(text),
            has_store_intent=self._has_store_intent(text),
            is_policy_intent=self._is_policy_intent(text),
            policy_topic_count=self._policy_topic_count(text),
            sku_token=self._extract_sku(text),
            requested_currency=requested_currency,
        )
        target_currency = (ctx.requested_currency or default_display_currency).upper()
        reply_language = await self._resolve_reply_language(user_text=ctx.text, locale=req.locale, run_id=run_id)
        debug_meta["reply_language"] = reply_language
        follow_up_options = await self._get_follow_up_questions(
            reply_language=reply_language,
            run_id=run_id,
        )
        response_renderer = self._response_renderer
        looks_like_product = ctx.looks_like_product
        sku_token = ctx.sku_token
        product_topk = int(getattr(settings, "PRODUCT_SEARCH_TOPK", settings.RAG_RETRIEVE_TOPK_PRODUCT))
        is_question_like = ctx.is_question_like
        has_store_intent = ctx.has_store_intent
        is_policy_intent = ctx.is_policy_intent
        policy_topic_count = ctx.policy_topic_count
        product_pipeline = self._product_pipeline
        knowledge_pipeline = self._knowledge_pipeline
        verifier_service = self._verifier_service

        cache_query_embedding: Optional[List[float]] = None
        cache_hit = False
        cache_eligible = bool(
            bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", True))
            and not history
            and not ctx.sku_token
            and not self._is_smalltalk(ctx.text)
            and not self._is_meta_question(ctx.text)
            and len((ctx.text or "").strip()) >= 10
        )
        debug_meta["cache_lookup"] = cache_eligible
        if cache_eligible:
            cache_query_embedding = await llm_service.generate_embedding(ctx.text)
            hit = await semantic_cache_service.get_hit(
                self.db,
                query_embedding=cache_query_embedding,
                reply_language=reply_language,
                target_currency=target_currency,
            )
            if hit and hit.entry and isinstance(hit.entry.response_json, dict):
                cached = hit.entry.response_json
                cache_hit = True
                debug_meta["cache_hit"] = True
                debug_meta["cache_id"] = hit.entry.id
                debug_meta["cache_distance"] = hit.distance
                response = ChatResponse(
                    conversation_id=conversation.id,
                    reply_text=str(cached.get("reply_text") or ""),
                    product_carousel=cached.get("product_carousel") or [],
                    follow_up_questions=cached.get("follow_up_questions") or [],
                    intent=str(cached.get("intent") or "knowledge"),
                    sources=cached.get("sources") or [],
                    debug=debug_meta,
                )
                debug_meta["route"] = response.intent
                return await self._finalize_response(
                    conversation_id=conversation.id,
                    user_text=ctx.text,
                    response=response,
                )
        debug_meta["cache_hit"] = cache_hit

        planner: Dict[str, Any] = {"used": False}
        planner_used = False
        planner_task = "general"
        planner_confidence = 0.0
        planner_min_conf = float(getattr(settings, "PLANNER_MIN_CONFIDENCE", 0.6))
        planner_is_smalltalk = False
        planner_is_meta = False
        planner_is_catalog_browse = False
        kb_query_text = ""
        product_query_text = ""

        if not sku_token:
            planner = await self._plan_retrieval(user_text=ctx.text, locale=req.locale, run_id=run_id)
            planner_used = bool(planner.get("used")) and not planner.get("error")
            planner_task = str(planner.get("task") or "general").strip().lower()
            planner_is_smalltalk = bool(planner.get("is_smalltalk"))
            planner_is_meta = bool(planner.get("is_meta_question"))
            planner_is_catalog_browse = bool(planner.get("is_catalog_browse"))
            try:
                planner_confidence = float(planner.get("confidence") or 0.0)
            except Exception:
                planner_confidence = 0.0

        planner_applied = planner_used and planner_confidence >= planner_min_conf
        if planner_used:
            debug_meta["planner_used"] = True
            debug_meta["planner_task"] = planner_task
            debug_meta["planner_confidence"] = planner_confidence
            debug_meta["planner_kb_query"] = planner.get("kb_query") or ""
            debug_meta["planner_product_query"] = planner.get("product_query") or ""
            debug_meta["planner_needs_clarification"] = bool(planner.get("needs_clarification"))
            debug_meta["planner_applied"] = planner_applied
            debug_meta["planner_is_smalltalk"] = planner_is_smalltalk
            debug_meta["planner_is_meta_question"] = planner_is_meta
            debug_meta["planner_is_catalog_browse"] = planner_is_catalog_browse
        else:
            debug_meta["planner_used"] = False

        if planner_used and planner_is_smalltalk and bool(getattr(settings, "SMALLTALK_ENABLED", True)):
            decision = RouteDecision(route="smalltalk", reason="planner_smalltalk")
            reply_text = await self._smalltalk_response(user_text=ctx.text, reply_language=reply_language)
            follow_ups = follow_up_options
            self._log_event(
                run_id=run_id,
                location="chat_service.route_selected",
                data={"route": "smalltalk", "reason": decision.reason, "planner_task": planner_task},
            )
            debug_meta["route"] = decision.route
            response = await response_renderer.render(
                conversation_id=conversation.id,
                route=decision.route,
                reply_text=reply_text,
                product_carousel=[],
                follow_up_questions=follow_ups,
                sources=[],
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=ctx.text,
                apply_polish=False,
            )
            return await self._finalize_response(
                conversation_id=conversation.id,
                user_text=ctx.text,
                response=response,
            )

        # Meta / general chat (LLM-only, no retrieval/verifier).
        if planner_used and planner_is_meta:
            decision = RouteDecision(route="general_chat", reason="planner_meta")
            try:
                reply_text = await self._general_chat_response(
                    user_text=ctx.text, reply_language=reply_language, history=history
                )
            except Exception as e:
                logger.error(f"general_chat generation failed: {e}")
                reply_text = await self._localize_ui_text(
                    reply_language=reply_language,
                    text="I am here to help. How may I assist you today?",
                    run_id=run_id,
                )
            self._log_event(
                run_id=run_id,
                location="chat_service.route_selected",
                data={"route": decision.route, "reason": decision.reason, "planner_task": planner_task},
            )
            debug_meta["route"] = decision.route
            response = await response_renderer.render(
                conversation_id=conversation.id,
                route=decision.route,
                reply_text=reply_text,
                product_carousel=[],
                follow_up_questions=follow_up_options,
                sources=[],
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=ctx.text,
                apply_polish=False,
            )
            return await self._finalize_response(
                conversation_id=conversation.id,
                user_text=ctx.text,
                response=response,
            )

        if planner_used and planner_is_catalog_browse:
            categories = await self._get_product_category_overview()
            if categories:
                preview = ", ".join(categories[:6])
                suggested = f"I can show categories like {preview}. Which category should I show?"
            else:
                suggested = "Which product category are you looking for?"
            reply_text = await self._generate_contextual_reply(
                user_text=ctx.text,
                reply_language=reply_language,
                suggested_question=suggested,
                focus="catalog_overview",
                telemetry=debug_meta,
                run_id=run_id,
                required_terms=categories[:6] if categories else None,
            )
            decision = RouteDecision(route="product", reason="planner_catalog_browse")
            self._log_event(
                run_id=run_id,
                location="chat_service.route_selected",
                data={"route": decision.route, "reason": decision.reason, "planner_task": planner_task},
            )
            debug_meta["route"] = decision.route
            response = await response_renderer.render(
                conversation_id=conversation.id,
                route=decision.route,
                reply_text=reply_text,
                product_carousel=[],
                follow_up_questions=[],
                sources=[],
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=ctx.text,
                apply_polish=False,
            )
            return await self._finalize_response(
                conversation_id=conversation.id,
                user_text=ctx.text,
                response=response,
            )

        # Fallback heuristic routes if planner is disabled or fails.
        if not planner_used:
            if bool(getattr(settings, "SMALLTALK_ENABLED", True)) and self._is_smalltalk(ctx.text):
                decision = RouteDecision(route="smalltalk", reason="heuristic_smalltalk")
                reply_text = await self._smalltalk_response(user_text=ctx.text, reply_language=reply_language)
                follow_ups = follow_up_options
                self._log_event(
                    run_id=run_id,
                    location="chat_service.route_selected",
                    data={"route": "smalltalk", "reason": decision.reason},
                )
                debug_meta["route"] = decision.route
                response = await response_renderer.render(
                    conversation_id=conversation.id,
                    route=decision.route,
                    reply_text=reply_text,
                    product_carousel=[],
                    follow_up_questions=follow_ups,
                    sources=[],
                    debug=debug_meta,
                    reply_language=reply_language,
                    target_currency=target_currency,
                    user_text=ctx.text,
                    apply_polish=False,
                )
                return await self._finalize_response(
                    conversation_id=conversation.id,
                    user_text=ctx.text,
                    response=response,
                )

            if self._is_meta_question(ctx.text) or self._is_general_chat(ctx.text):
                decision = RouteDecision(route="general_chat", reason="heuristic_meta_or_general")
                try:
                    reply_text = await self._general_chat_response(
                        user_text=ctx.text, reply_language=reply_language, history=history
                    )
                except Exception as e:
                    logger.error(f"general_chat generation failed: {e}")
                    reply_text = await self._localize_ui_text(
                        reply_language=reply_language,
                        text="Hello, I am here to help. How may I assist you today?",
                        run_id=run_id,
                    )
                self._log_event(
                    run_id=run_id,
                    location="chat_service.route_selected",
                    data={"route": decision.route, "reason": decision.reason},
                )
                debug_meta["route"] = decision.route
                response = await response_renderer.render(
                    conversation_id=conversation.id,
                    route=decision.route,
                    reply_text=reply_text,
                    product_carousel=[],
                    follow_up_questions=follow_up_options,
                    sources=[],
                    debug=debug_meta,
                    reply_language=reply_language,
                    target_currency=target_currency,
                    user_text=ctx.text,
                    apply_polish=False,
                )
                return await self._finalize_response(
                    conversation_id=conversation.id,
                    user_text=ctx.text,
                    response=response,
                )

        if planner_applied and planner_task == "general":
            decision = RouteDecision(route="general_chat", reason="planner_general")
            try:
                reply_text = await self._general_chat_response(user_text=ctx.text, reply_language=reply_language, history=history)
            except Exception as e:
                logger.error(f"general_chat generation failed: {e}")
                reply_text = await self._localize_ui_text(
                    reply_language=reply_language,
                    text="Hello, I am here to help. How may I assist you today?",
                    run_id=run_id,
                )
            self._log_event(
                run_id=run_id,
                location="chat_service.route_selected",
                data={"route": decision.route, "planner_task": planner_task},
            )
            debug_meta["route"] = decision.route
            response = await response_renderer.render(
                conversation_id=conversation.id,
                route=decision.route,
                reply_text=reply_text,
                product_carousel=[],
                follow_up_questions=follow_up_options,
                sources=[],
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=ctx.text,
                apply_polish=False,
            )
            return await self._finalize_response(
                conversation_id=conversation.id,
                user_text=ctx.text,
                response=response,
            )

        if planner_applied and bool(planner.get("needs_clarification")):
            decision = RouteDecision(route="clarify", reason="planner_clarify")
            clarifier = str(planner.get("clarifying_question") or "").strip()
            default_clarifier = "What would you like to know about our products or policies?"
            if planner_task in {"product_search", "mixed"}:
                default_clarifier = "Which product category or SKU are you interested in?"
            elif planner_task in {"policy", "shipping_region"}:
                default_clarifier = "Are you asking about shipping availability, shipping cost, or delivery time?"
            elif planner_task == "contact":
                default_clarifier = "Do you want a phone number, email, or WhatsApp contact?"

            if not clarifier or self._is_echo_clarifier(user_text=ctx.text, clarifier=clarifier):
                clarifier = default_clarifier

            reply_text = await self._generate_contextual_reply(
                user_text=ctx.text,
                reply_language=reply_language,
                suggested_question=clarifier,
                focus=f"planner:{planner_task}",
                telemetry=debug_meta,
                run_id=run_id,
            )

            debug_meta["route"] = decision.route
            response = await response_renderer.render(
                conversation_id=conversation.id,
                route=decision.route,
                reply_text=reply_text,
                product_carousel=[],
                follow_up_questions=[],
                sources=[],
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=ctx.text,
                apply_polish=False,
            )
            return await self._finalize_response(
                conversation_id=conversation.id,
                user_text=ctx.text,
                response=response,
            )

        if planner_applied and planner_task in {"product_search", "policy", "shipping_region", "contact", "mixed"}:
            is_question_like = True

        use_products = looks_like_product
        use_knowledge = True
        if planner_applied:
            use_products = planner_task in {"product_search", "mixed"}
            use_knowledge = planner_task in {"policy", "shipping_region", "contact", "mixed"}
            looks_like_product = looks_like_product or use_products
            is_policy_intent = is_policy_intent or planner_task in {"policy", "shipping_region", "mixed"}
            has_store_intent = has_store_intent or planner_task in {"product_search", "policy", "shipping_region", "contact", "mixed"}
            if planner_task in {"policy", "shipping_region"} and policy_topic_count == 0:
                policy_topic_count = 1

        if planner_applied:
            kb_query_text = str(planner.get("kb_query") or "").strip()
            product_query_text = str(planner.get("product_query") or "").strip()
        if not kb_query_text:
            kb_query_text = ctx.text
        if not product_query_text:
            product_query_text = ctx.text

        is_complex = is_question_like and self._is_complex_query(kb_query_text)
        max_sub_questions = int(getattr(settings, "RAG_MAX_SUB_QUESTIONS", 4))
        self._log_event(
            run_id=run_id,
            location="chat_service.rag.complexity_check",
            data={
                "is_complex": is_complex,
                "is_question_like": is_question_like,
                "policy_topic_count": policy_topic_count,
                "len": len(ctx.text),
                "max_sub_questions": max_sub_questions,
                "planner_used": planner_used,
                "planner_task": planner_task,
            },
        )

        # SKU shortcut (must-have): direct DB lookup without embeddings.
        if sku_token:
            sku_cards = await product_pipeline.sku_shortcut(sku=sku_token, limit=product_topk)
            if sku_cards:
                decision = RouteDecision(route="product", reason="sku_shortcut")
                self._log_event(
                    run_id=run_id,
                    location="chat_service.product.sku_shortcut",
                    data={"matched_sku": sku_token, "count": len(sku_cards)},
                )

                price_intent = bool(re.search(r"\b(price|cost)\b", ctx.text.lower()))
                if price_intent:
                    p0 = sku_cards[0]
                    converted = currency_service.convert(
                        float(p0.price),
                        from_currency=str(p0.currency or settings.BASE_CURRENCY),
                        to_currency=target_currency,
                    )
                    amount_str = str(round(float(converted.amount), 2))
                    reply_text = await self._localize_price_sentence(
                        sku=p0.sku,
                        amount=amount_str,
                        currency=str(converted.currency),
                        reply_language=reply_language,
                        run_id=run_id,
                    )
                else:
                    reply_text = await self._localize_ui_text(
                        reply_language=reply_language,
                        text="Here are some products that might help:",
                        run_id=run_id,
                    )

                debug_meta["route"] = decision.route
                response = await response_renderer.render(
                    conversation_id=conversation.id,
                    route=decision.route,
                    reply_text=reply_text,
                    product_carousel=sku_cards,
                    follow_up_questions=[],
                    sources=[],
                    debug=debug_meta,
                    target_currency=target_currency,
                    user_text=ctx.text,
                    apply_polish=False,
                )
                return await self._finalize_response(
                    conversation_id=conversation.id,
                    user_text=ctx.text,
                    response=response,
                )

        sub_questions: List[str] = []
        knowledge_query_text = kb_query_text
        knowledge_embedding = None
        product_embedding = None

        if use_products and use_knowledge and product_query_text == knowledge_query_text:
            shared_embedding = await llm_service.generate_embedding(product_query_text)
            product_embedding = shared_embedding
            knowledge_embedding = shared_embedding
        else:
            if use_products:
                product_embedding = await llm_service.generate_embedding(product_query_text)
            if use_knowledge:
                knowledge_embedding = await llm_service.generate_embedding(knowledge_query_text)

        product_result = await product_pipeline.run(
            ctx=ctx,
            product_embedding=product_embedding,
            product_topk=product_topk,
            use_products=use_products,
            is_policy_intent=is_policy_intent,
            looks_like_product=looks_like_product,
            run_id=run_id,
        )
        product_cards = product_result.product_cards
        product_top_distances = product_result.product_top_distances
        product_best = product_result.product_best
        product_gate_decision = product_result.product_gate_decision

        if product_gate_decision in {"strict", "loose"} and product_cards:
            decision = RouteDecision(route="product", reason="product_gate")
            reply_text = await self._localize_ui_text(
                reply_language=reply_language,
                text="Here are some products that might help:",
                run_id=run_id,
            )
            debug_meta["route"] = decision.route
            response = await response_renderer.render(
                conversation_id=conversation.id,
                route=decision.route,
                reply_text=reply_text,
                product_carousel=product_cards,
                follow_up_questions=[],
                sources=[],
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=ctx.text,
                apply_polish=False,
            )
            return await self._finalize_response(
                conversation_id=conversation.id,
                user_text=ctx.text,
                response=response,
            )

        if not use_knowledge:
            categories: List[str] = []
            catalog_browse = bool(planner_used and planner_is_catalog_browse) or (
                not planner_used and self._is_catalog_browse(ctx.text)
            )
            if catalog_browse:
                categories = await self._get_product_category_overview()
                if categories:
                    preview = ", ".join(categories[:6])
                    reply_text = f"I can show categories like {preview}. Which category should I show?"
                else:
                    reply_text = "Which product category should I show?"
                route = "product"
            else:
                reply_text = "Which product category or SKU are you interested in?"
                route = "clarify"

            reply_text = await self._generate_contextual_reply(
                user_text=ctx.text,
                reply_language=reply_language,
                suggested_question=reply_text,
                focus="catalog_browse" if categories else "product_clarifier",
                telemetry=debug_meta,
                run_id=run_id,
                required_terms=categories[:6] if categories else None,
            )

            decision = RouteDecision(route=route, reason="planner_no_knowledge")
            debug_meta["route"] = decision.route
            response = await response_renderer.render(
                conversation_id=conversation.id,
                route=decision.route,
                reply_text=reply_text,
                product_carousel=[],
                follow_up_questions=[],
                sources=[],
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=ctx.text,
                apply_polish=False,
            )
            return await self._finalize_response(
                conversation_id=conversation.id,
                user_text=ctx.text,
                response=response,
            )

        knowledge_result = await knowledge_pipeline.run(
            ctx=ctx,
            knowledge_query_text=knowledge_query_text,
            knowledge_embedding=knowledge_embedding,
            is_complex=is_complex,
            is_question_like=is_question_like,
            is_policy_intent=is_policy_intent,
            policy_topic_count=policy_topic_count,
            max_sub_questions=max_sub_questions,
            run_id=run_id,
        )

        retrieval = knowledge_result.retrieval
        rerank_result = knowledge_result.rerank

        debug_meta["decomposition_used"] = retrieval.decomposition_used
        debug_meta["decomposition_reason"] = retrieval.decomposition_reason
        debug_meta["decomposition_knowledge_best"] = retrieval.decomposition_knowledge_best
        debug_meta["decomposition_gap"] = retrieval.decomposition_gap

        knowledge_sources = retrieval.knowledge_sources
        knowledge_best = retrieval.knowledge_best
        knowledge_top_distances = retrieval.knowledge_top_distances
        sub_questions = retrieval.sub_questions
        per_query_keep = retrieval.per_query_keep

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
        
        # Low-confidence retrieval gate: avoid verifier producing unrelated clarifications.
        product_weak_thr = float(getattr(settings, "PRODUCT_WEAK_DISTANCE", 0.55))
        knowledge_weak_thr = float(getattr(settings, "KNOWLEDGE_WEAK_DISTANCE", 0.60))
        product_weak = (product_best is None) or (float(product_best) >= product_weak_thr)
        knowledge_weak = (knowledge_best is None) or (float(knowledge_best) >= knowledge_weak_thr)
        if product_weak and knowledge_weak:
            has_store_intent = ctx.has_store_intent
            if has_store_intent:
                categories: List[str] = []
                catalog_browse = bool(planner_used and planner_is_catalog_browse) or (
                    not planner_used and self._is_catalog_browse(ctx.text)
                )
                if catalog_browse:
                    categories = await self._get_product_category_overview()
                    if categories:
                        preview = ", ".join(categories[:6])
                        reply_text = f"I can show categories like {preview}. Which category should I show?"
                    else:
                        reply_text = "Which product category should I show?"
                    route = "product"
                    weak_retrieval_action = "catalog_overview"
                else:
                    reply_text = "Which product category or SKU are you interested in?"
                    route = "clarify"
                    weak_retrieval_action = "targeted_clarifier"
                reply_text = await self._generate_contextual_reply(
                    user_text=ctx.text,
                    reply_language=reply_language,
                    suggested_question=reply_text,
                    focus=weak_retrieval_action,
                    telemetry=debug_meta,
                    run_id=run_id,
                    required_terms=categories[:6] if categories else None,
                )
                follow_ups = []
            else:
                route = "general_chat"
                try:
                    reply_text = await self._general_chat_response(user_text=ctx.text, reply_language=reply_language, history=history)
                except Exception as e:
                    logger.error(f"general_chat generation failed: {e}")
                    reply_text = await self._localize_ui_text(
                        reply_language=reply_language,
                        text="Hello, what would you like to discuss today?",
                        run_id=run_id,
                    )
                follow_ups = follow_up_options
                weak_retrieval_action = "general_chat"

            decision = RouteDecision(route=route, reason="weak_retrieval")
            self._log_event(
                run_id=run_id,
                location="chat_service.route_selected",
                data={
                    "route": decision.route,
                    "fallback_general_triggered": route == "fallback_general",
                    "reason": "weak_retrieval",
                    "product_best": product_best,
                    "knowledge_best": knowledge_best,
                    "product_weak_thr": product_weak_thr,
                    "knowledge_weak_thr": knowledge_weak_thr,
                    "verifier_skipped_reason": "weak_retrieval",
                    "store_intent": has_store_intent,
                    "weak_retrieval_action": weak_retrieval_action,
                },
            )
            debug_meta["weak_retrieval_action"] = weak_retrieval_action
            debug_meta["route"] = decision.route
            response = await response_renderer.render(
                conversation_id=conversation.id,
                route=decision.route,
                reply_text=reply_text,
                product_carousel=[],
                follow_up_questions=follow_ups,
                sources=[],
                debug=debug_meta,
                reply_language=reply_language,
                target_currency=target_currency,
                user_text=ctx.text,
                apply_polish=False,
            )
            return await self._finalize_response(
                conversation_id=conversation.id,
                user_text=ctx.text,
                response=response,
            )

        reranked_top = rerank_result.reranked_top
        debug_meta["rerank_used"] = rerank_result.rerank_used
        debug_meta["rerank_reason"] = rerank_result.rerank_reason
        debug_meta["rerank_duration_ms"] = rerank_result.rerank_duration_ms
        debug_meta["rerank_timed_out"] = rerank_result.rerank_timed_out
        debug_meta["rerank_candidates"] = rerank_result.candidates_count
        debug_meta["rerank_d1"] = rerank_result.d1
        debug_meta["rerank_d10"] = rerank_result.d10
        debug_meta["rerank_gap"] = rerank_result.gap

        knowledge_strong_thr = float(getattr(settings, "KNOWLEDGE_DISTANCE_THRESHOLD", 0.40))
        product_strong_thr = float(getattr(settings, "PRODUCT_DISTANCE_STRICT", 0.35))
        knowledge_strong = knowledge_best is not None and float(knowledge_best) <= knowledge_strong_thr
        product_strong = product_best is not None and float(product_best) <= product_strong_thr
        if not is_complex:
            if knowledge_strong and (product_weak or not product_cards):
                fast_sources = reranked_top or knowledge_sources[: int(getattr(settings, "RAG_RERANK_TOPN", 5))]
                reply_text = await self.synthesize_answer(
                    ctx.text,
                    fast_sources,
                    reply_language,
                    run_id=run_id,
                )
                decision = RouteDecision(route="knowledge", reason="fast_path_knowledge")
                self._log_event(
                    run_id=run_id,
                    location="chat_service.route_selected",
                    data={
                        "route": decision.route,
                        "reason": decision.reason,
                        "knowledge_best": knowledge_best,
                        "product_best": product_best,
                        "verifier_skipped_reason": "fast_path_knowledge",
                    },
                )
                debug_meta["route"] = decision.route
                debug_meta["verifier_skipped_reason"] = "fast_path_knowledge"
                response = await response_renderer.render(
                    conversation_id=conversation.id,
                    route=decision.route,
                    reply_text=reply_text,
                    product_carousel=[],
                    follow_up_questions=[],
                    sources=fast_sources,
                    debug=debug_meta,
                    target_currency=target_currency,
                    user_text=ctx.text,
                    apply_polish=True,
                )
                return await self._finalize_response(
                    conversation_id=conversation.id,
                    user_text=ctx.text,
                    response=response,
                )

            if product_cards and product_strong and knowledge_weak:
                reply_text = sku_price_reply or await self._localize_ui_text(
                    reply_language=reply_language,
                    text="Here are some products that might help:",
                    run_id=run_id,
                )
                decision = RouteDecision(route="product", reason="fast_path_product")
                self._log_event(
                    run_id=run_id,
                    location="chat_service.route_selected",
                    data={
                        "route": decision.route,
                        "reason": decision.reason,
                        "knowledge_best": knowledge_best,
                        "product_best": product_best,
                        "verifier_skipped_reason": "fast_path_product",
                    },
                )
                debug_meta["route"] = decision.route
                debug_meta["verifier_skipped_reason"] = "fast_path_product"
                response = await response_renderer.render(
                    conversation_id=conversation.id,
                    route=decision.route,
                    reply_text=reply_text,
                    product_carousel=product_cards,
                    follow_up_questions=[],
                    sources=[],
                    debug=debug_meta,
                    target_currency=target_currency,
                    user_text=ctx.text,
                    apply_polish=False,
                )
                return await self._finalize_response(
                    conversation_id=conversation.id,
                    user_text=ctx.text,
                    response=response,
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

        decision = await verifier_service.verify(
            question=ctx.text,
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
                reply_text = await self._localize_ui_text(
                    reply_language=reply_language,
                    text="Here are some products that might help:",
                    run_id=run_id,
                )
                product_carousel = product_cards
                sources = []
                follow_up_questions = []
            elif answer_type == "mixed":
                route = "mixed"
                reply_text = await self.synthesize_answer(
                    ctx.text,
                    selected_sources,
                    reply_language,
                    run_id=run_id,
                )
                product_carousel = []
                sources = selected_sources
                follow_up_questions = []
            else:
                route = "knowledge"
                reply_text = await self.synthesize_answer(
                    ctx.text,
                    selected_sources,
                    reply_language,
                    run_id=run_id,
                )
                product_carousel = []
                sources = selected_sources
                follow_up_questions = []
        else:
            product_weak_thr = float(getattr(settings, "PRODUCT_WEAK_DISTANCE", 0.55))
            knowledge_weak_thr = float(getattr(settings, "KNOWLEDGE_WEAK_DISTANCE", 0.60))
            product_weak = (product_best is None) or (float(product_best) >= product_weak_thr)
            knowledge_weak = (knowledge_best is None) or (float(knowledge_best) >= knowledge_weak_thr)

            if self._is_question_like(ctx.text) and not (product_weak and knowledge_weak):
                route = "clarify"
                clarifier = missing_parts_q or (missing_q.strip() if isinstance(missing_q, str) else "")
                if selected_sources and effective_supporting_ids and clarifier:
                    reply_text = await self.synthesize_partial_answer(
                        original_question=ctx.text,
                        sources=selected_sources,
                        answerable_topics=answerable_topics,
                        missing_question=clarifier,
                        reply_language=reply_language,
                        run_id=run_id,
                    )
                    sources = selected_sources
                elif clarifier:
                    reply_text = await self._generate_contextual_reply(
                        user_text=ctx.text,
                        reply_language=reply_language,
                        suggested_question=clarifier,
                        focus="clarify",
                        telemetry=debug_meta,
                        run_id=run_id,
                    )
                    sources = []
                else:
                    reply_text = await self._generate_contextual_reply(
                        user_text=ctx.text,
                        reply_language=reply_language,
                        suggested_question="Could you clarify what exactly you want to know (one detail)?",
                        focus="clarify",
                        telemetry=debug_meta,
                        run_id=run_id,
                    )
                    sources = []
                product_carousel = []
                follow_up_questions = []
            else:
                route = "fallback_general"
                reply_text = await self._generate_contextual_reply(
                    user_text=ctx.text,
                    reply_language=reply_language,
                    suggested_question=(
                        "I can help you browse products or answer store questions. What would you like to do?"
                    ),
                    focus="fallback_general",
                    telemetry=debug_meta,
                    run_id=run_id,
                )
                product_carousel = []
                sources = []
                follow_up_questions = await self._get_follow_up_questions(
                    reply_language=reply_language,
                    run_id=run_id,
                )

        decision = RouteDecision(route=route, reason="verifier")
        self._log_event(
            run_id=run_id,
            location="chat_service.rag.route_decision",
            data={
                "route": decision.route,
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
                "route": decision.route,
            },
        )

        debug_meta["route"] = decision.route

        response = await response_renderer.render(
            conversation_id=conversation.id,
            route=decision.route,
            reply_text=reply_text,
            product_carousel=product_carousel,
            follow_up_questions=follow_up_questions,
            sources=sources,
            debug=debug_meta,
            target_currency=target_currency,
            user_text=ctx.text,
            apply_polish=True,
        )
        if cache_eligible and (not cache_hit) and cache_query_embedding is not None and response.intent in {"knowledge", "mixed"}:
            try:
                def _dump(item: Any) -> Any:
                    if hasattr(item, "model_dump"):
                        return item.model_dump()
                    if hasattr(item, "dict"):
                        return item.dict()
                    return item

                payload = {
                    "reply_text": response.reply_text,
                    "product_carousel": [_dump(p) for p in (response.product_carousel or [])],
                    "follow_up_questions": list(response.follow_up_questions or []),
                    "intent": response.intent,
                    "sources": [_dump(s) for s in (response.sources or [])],
                }
                await semantic_cache_service.save_hit(
                    self.db,
                    query_text=ctx.text,
                    query_embedding=cache_query_embedding,
                    response_json=payload,
                    reply_language=reply_language,
                    target_currency=target_currency,
                )
                debug_meta["cache_saved"] = True
            except Exception as e:
                debug_meta["cache_saved"] = False
                debug_meta["cache_save_error"] = str(e)
        return await self._finalize_response(
            conversation_id=conversation.id,
            user_text=ctx.text,
            response=response,
        )
