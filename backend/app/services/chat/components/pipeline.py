from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
import re
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat import Conversation, Message
from app.models.product import Product, StockStatus
from app.models.product_search_projection import ProductSearchProjection
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatResponseMeta,
    KnowledgeSource,
    ProductCard,
)
from app.services.ai.llm_service import llm_service
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.chat import conversation_state, product_presentation, reply_tone, result_policy, routing_policy
from app.services.chat.components.cache import RedisComponentCache, stable_cache_key
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.field_resolver import FieldDependencyResolver
from app.services.chat.components.registry import ComponentRegistry
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.detail_query_parser import DetailQueryParser
from app.services.chat.detail_response_builder import DetailResponseBuilder
from app.services.chat.product_detail_resolver import ProductDetailResolver
from app.services.chat.recommendation_service import RecommendationService
from app.services.knowledge.retrieval import KnowledgeRetrievalService


@dataclass
class ComponentPipelineResult:
    response: ChatResponse
    detail_mode_triggered: bool
    llm_calls: int
    embedding_calls: int
    external_call_counts: Dict[str, int] = field(default_factory=dict)
    spans: Dict[str, float] = field(default_factory=dict)
    debug: Dict[str, Any] = field(default_factory=dict)
    conversation_state: Optional[Dict[str, Any]] = None


class ComponentPipeline:
    _ATTRIBUTE_LIST_TERMS = {
        "material": "material",
        "materials": "material",
        "color": "color",
        "colors": "color",
        "gauge": "gauge",
        "gauges": "gauge",
        "threading": "threading",
        "threadings": "threading",
        "type": "jewelry_type",
        "types": "jewelry_type",
    }
    _DETAIL_CLARIFY_FIELDS = {"price", "stock"}
    _HIGH_RISK_KNOWLEDGE_TERMS = {
        "shipping",
        "delivery",
        "refund",
        "return",
        "payment",
        "warranty",
        "customs",
        "contact",
        "sales contact",
        "sales team",
        "support",
        "customer service",
        "email",
        "phone",
        "hotline",
        "whatsapp",
    }
    _CONTACT_KNOWLEDGE_TERMS = {
        "contact",
        "sales contact",
        "sales team",
        "support",
        "customer service",
        "email",
        "phone",
        "hotline",
        "whatsapp",
    }
    _LOCATION_KNOWLEDGE_TERMS = {
        "where",
        "location",
        "address",
        "showroom",
        "in person",
        "visit",
        "pickup",
        "pick up",
    }
    _SHIPPING_KNOWLEDGE_TERMS = {"shipping", "delivery", "lead time", "arrive", "ship"}
    _REFUND_KNOWLEDGE_TERMS = {"refund", "return", "exchange"}
    _PAYMENT_KNOWLEDGE_TERMS = {"payment", "pay", "invoice", "wire", "bank transfer", "credit card"}
    _WARRANTY_KNOWLEDGE_TERMS = {"warranty", "guarantee"}
    _KNOWLEDGE_UNAVAILABLE_MESSAGE = "I can share a short answer now, but detailed knowledge search is unavailable."
    _DESIGN_DISCOVERY_TERMS = ("design", "style", "look", "aesthetic")
    _FALLBACK_VALID_HINTS = (
        "labret",
        "barbell",
        "ring",
        "opal",
        "titanium",
        "steel",
        "gold",
        "shipping",
        "refund",
        "contact",
        "policy",
        "price",
        "stock",
        "recommend",
    )
    _OFF_TOPIC_REDIRECT_OPTIONS = (
        "If you want, tell me what jewelry type or material you're looking for.",
        "If you want, ask me about products, stock, or store policies.",
        "If you want, share your preferred style and I can suggest products.",
    )

    def __init__(
        self,
        *,
        db: AsyncSession,
        catalog_search: CatalogProductSearchService,
        knowledge_retrieval: KnowledgeRetrievalService,
        redis_cache: RedisComponentCache,
    ):
        self.db = db
        self._catalog_search = catalog_search
        self._knowledge_retrieval = knowledge_retrieval
        self._redis_cache = redis_cache
        self._field_resolver = FieldDependencyResolver(db=db)
        self._recommendation_service = RecommendationService(db=db, catalog_search=catalog_search)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text or "").strip().lower().split())

    @staticmethod
    def _dedupe_follow_up_questions(items: Sequence[str], *, limit: int = 5) -> List[str]:
        deduped: List[str] = []
        seen: set[str] = set()
        for raw in list(items or []):
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(text)
            if len(deduped) >= max(1, int(limit)):
                break
        return deduped

    @classmethod
    def _contains_any_term(cls, *, text: str, terms: Sequence[str]) -> bool:
        normalized = cls._normalize_text(text)
        return bool(normalized and any(term in normalized for term in terms))

    @classmethod
    def _is_high_risk_knowledge_request(cls, *, text: str) -> bool:
        return cls._contains_any_term(text=text, terms=cls._HIGH_RISK_KNOWLEDGE_TERMS)

    @staticmethod
    def _knowledge_sources_are_weak(*, sources: Sequence[KnowledgeSource], min_relevance: float) -> bool:
        if not sources:
            return True
        top_relevance = max(float(getattr(source, "relevance", 0.0) or 0.0) for source in list(sources or []))
        return top_relevance < float(min_relevance)

    @staticmethod
    def _product_sku(product: Any) -> str:
        return str(getattr(product, "sku", "") or "").strip()

    @classmethod
    def _build_product_clarify_follow_ups(
        cls,
        *,
        products: Sequence[Any],
        attribute_filters: Dict[str, str],
        needs_knowledge: bool,
        limit: int = 3,
    ) -> List[str]:
        follow_ups: List[str] = []
        for product in list(products or [])[:3]:
            sku = cls._product_sku(product)
            if sku:
                follow_ups.append(f"Show details for SKU {sku}")
        if not follow_ups:
            if "material" not in attribute_filters:
                follow_ups.extend(["Show titanium jewelry", "Show gold jewelry"])
            if "jewelry_type" not in attribute_filters:
                follow_ups.append("Show labret")
        if needs_knowledge:
            follow_ups.append("How can I contact you?")
        return cls._dedupe_follow_up_questions(follow_ups, limit=limit)

    @classmethod
    def _build_knowledge_clarify_follow_ups(
        cls,
        *,
        user_text: str,
        limit: int = 3,
    ) -> List[str]:
        focus = cls._knowledge_clarify_focus(user_text=user_text)
        if focus in {"contact", "location"}:
            return cls._dedupe_follow_up_questions(
                [
                    "What is your sales email?",
                    "What is your phone number?",
                    "What is your showroom address?",
                ],
                limit=limit,
            )
        if focus == "shipping":
            return cls._dedupe_follow_up_questions(
                [
                    "What is your shipping policy?",
                    "How long is delivery?",
                    "Do you ship internationally?",
                ],
                limit=limit,
            )
        if focus == "refund":
            return cls._dedupe_follow_up_questions(
                [
                    "What is your refund policy?",
                    "What can I return?",
                    "How long do refunds take?",
                ],
                limit=limit,
            )
        if focus == "payment":
            return cls._dedupe_follow_up_questions(
                [
                    "What payment methods do you accept?",
                    "Can I pay by bank transfer?",
                    "Do you issue invoices?",
                ],
                limit=limit,
            )
        if focus == "warranty":
            return cls._dedupe_follow_up_questions(
                [
                    "What is your warranty policy?",
                    "What does the warranty cover?",
                    "How do I claim warranty support?",
                ],
                limit=limit,
            )
        normalized = cls._normalize_text(user_text)
        follow_ups: List[str] = []
        if "shipping" in normalized or "delivery" in normalized:
            follow_ups.extend(["What is your shipping policy?", "How long is delivery?"])
        if "refund" in normalized or "return" in normalized:
            follow_ups.extend(["What is your refund policy?", "What can I return?"])
        if any(term in normalized for term in {"contact", "support", "sales", "email", "phone", "whatsapp"}):
            follow_ups.extend(["How can I contact you?", "How can I contact your sales team?"])
        if not follow_ups:
            follow_ups.extend(
                [
                    "What is your shipping policy?",
                    "What is your refund policy?",
                    "How can I contact you?",
                ]
            )
        return cls._dedupe_follow_up_questions(follow_ups, limit=limit)

    @classmethod
    def _knowledge_clarify_focus(cls, *, user_text: str) -> str:
        normalized = cls._normalize_text(user_text)
        if not normalized:
            return "general"
        if any(term in normalized for term in cls._LOCATION_KNOWLEDGE_TERMS):
            return "location"
        if any(term in normalized for term in cls._CONTACT_KNOWLEDGE_TERMS):
            return "contact"
        if any(term in normalized for term in cls._SHIPPING_KNOWLEDGE_TERMS):
            return "shipping"
        if any(term in normalized for term in cls._REFUND_KNOWLEDGE_TERMS):
            return "refund"
        if any(term in normalized for term in cls._PAYMENT_KNOWLEDGE_TERMS):
            return "payment"
        if any(term in normalized for term in cls._WARRANTY_KNOWLEDGE_TERMS):
            return "warranty"
        return "general"

    @classmethod
    def _knowledge_clarify_question(cls, *, user_text: str) -> str:
        focus = cls._knowledge_clarify_focus(user_text=user_text)
        if focus in {"contact", "location"}:
            return "Do you need our sales email, phone number, or showroom address?"
        if focus == "shipping":
            return "Do you need shipping cost, delivery time, or destination coverage?"
        if focus == "refund":
            return "Do you need return eligibility, refund timing, or exchange terms?"
        if focus == "payment":
            return "Do you need accepted payment methods, invoice details, or transfer instructions?"
        if focus == "warranty":
            return "Do you need warranty coverage, duration, or claim steps?"
        return "Which policy detail do you need?"

    @classmethod
    def _build_clarify_policy(
        cls,
        *,
        reason: str,
        user_text: str,
        tone_pick: Callable[[str, Sequence[str]], str],
        products: Sequence[Any],
        attribute_filters: Dict[str, str],
        needs_knowledge: bool,
        requested_fields: Sequence[str],
    ) -> Dict[str, Any]:
        reason_norm = str(reason or "missing_details").strip() or "missing_details"
        message = ""
        questions: List[str] = []
        suggestions: List[str] = []
        extra_debug: Dict[str, Any] = {}

        if reason_norm == "challenge_target_clarification":
            message = "I can verify that for you. Please share the SKU or exact product name you are referring to."
            questions = ["Which SKU or product should I verify?"]
            suggestions = ["Check stock for SKU ABC-1", "The product with SKU ABC-1 is out of stock"]
        elif reason_norm == "challenge_target_not_found":
            message = "I could not find that SKU in our inventory. Please check the SKU and resend it."
            questions = ["Can you resend the exact SKU code?"]
        elif reason_norm == "image_only_no_results":
            message = tone_pick(
                "clarify:image_only_no_results",
                [
                    "I couldn't find matching products with images right now. You can ask by SKU, price, or stock.",
                    "No matching items with images yet. Try asking by SKU, price, or stock.",
                    "I can't find image results for that query. Ask by SKU, price, or stock and I can continue.",
                ],
            )
            questions = ["Do you want to search by SKU, price, or stock?"]
        elif reason_norm == "image_request_missing_context":
            message = "Sure, which product are you looking for? Share SKU or details like type, material, and gauge, and I can show images."
            questions = ["What product should I show images for?"]
        elif reason_norm == "attribute_list_no_results":
            message = tone_pick(
                "clarify:attribute_list_no_results",
                [
                    "I couldn't find matching options for that filter. Try a broader filter.",
                    "No matching attribute options yet. Try removing one filter and search again.",
                    "That filter is too narrow right now. Try a broader attribute filter.",
                ],
            )
            questions = ["Which filter do you want to broaden?"]
        elif reason_norm == "structured_no_match":
            questions = ["Which item should I narrow down for you?"]
            if cls._is_design_discovery_query(
                user_text=user_text,
                attribute_filters=attribute_filters,
            ):
                message = tone_pick(
                    "clarify:structured_no_match:design_discovery",
                    [
                        "Great question. We carry minimalist, opal, and statement body jewelry styles. Tell me your piercing type and preferred style and I'll narrow it down.",
                        "We have a range of clean, opal, and bold designs. Share your piercing type and style preference and I'll suggest the best matches.",
                        "We offer both subtle and standout body jewelry designs. Tell me your style and piercing type, and I'll shortlist options.",
                    ],
                )
                questions = ["Do you want subtle, bold, or opal-focused designs?"]
            else:
                message = tone_pick(
                    "clarify:structured_no_match:humanized",
                    [
                        "I can still help here. Share one preference like material, style, or gauge and I'll narrow options.",
                        "No exact match yet, but I can find alternatives. Tell me one preference and I'll refine the search.",
                        "I can quickly narrow this down. Share one detail like material or style and I'll show the closest options.",
                    ],
                )
        elif reason_norm == "detail_no_match":
            message = tone_pick(
                "clarify:detail_no_match",
                [
                    "I couldn't find a product matching those exact details. Try a broader request or share a SKU.",
                    "I don't see an exact product match yet. Share a SKU or broader details and I'll retry.",
                    "No exact product match found. Send a SKU or fewer filters and I can narrow it down.",
                ],
            )
            questions = ["Can you share a SKU or fewer filters?"]
        elif reason_norm == "detail_request_needs_specific_product":
            requested = {str(item or "").strip().lower() for item in list(requested_fields or []) if str(item or "").strip()}
            jewelry_type = str((attribute_filters or {}).get("jewelry_type") or "").strip().lower()
            subject = jewelry_type or "product"
            action = "look that up"
            if "price" in requested and "stock" in requested:
                action = "check the price and stock"
            elif "price" in requested:
                action = "check the price"
            elif "stock" in requested:
                action = "check the stock"
            message = f"I'm not sure which {subject} you mean. Share a SKU or add details like material, gauge, size, or color, and I can {action}."
            questions = ["Which exact product should I use?"]
        elif reason_norm in {"knowledge_needs_clarification", "knowledge_unavailable"}:
            knowledge_focus = cls._knowledge_clarify_focus(user_text=user_text)
            knowledge_question = cls._knowledge_clarify_question(user_text=user_text)
            if reason_norm == "knowledge_needs_clarification":
                if knowledge_focus in {"contact", "location"}:
                    message = tone_pick(
                        "clarify:knowledge_contact_context",
                        [
                            "I can share that. Do you need our sales email, phone number, or showroom address?",
                            "Happy to help with contact details. Should I send email, phone, or showroom address?",
                            "I can provide contact info now. Do you want email, phone, or showroom address?",
                        ],
                    )
                else:
                    message = tone_pick(
                        "clarify:knowledge_context",
                        [
                            f"I can help with that. {knowledge_question}",
                            f"To answer accurately, I need one detail. {knowledge_question}",
                            f"Let's narrow this quickly. {knowledge_question}",
                        ],
                    )
            else:
                if knowledge_focus in {"contact", "location"}:
                    message = tone_pick(
                        "clarify:knowledge_contact_unavailable",
                        [
                            "I may be missing the latest contact detail. Do you need email, phone, or showroom address?",
                            "I can help with contact info. Tell me whether you need email, phone, or address.",
                            "I need one detail to continue: email, phone, or showroom address?",
                        ],
                    )
                else:
                    message = tone_pick(
                        "clarify:knowledge_unavailable",
                        [
                            f"I may be missing the latest policy details. {knowledge_question}",
                            f"I can still help, but I need a specific policy topic. {knowledge_question}",
                            f"To avoid guessing, I need one specific detail. {knowledge_question}",
                        ],
                    )
            questions = [knowledge_question]
            suggestions = cls._build_knowledge_clarify_follow_ups(user_text=user_text, limit=3)
            extra_debug["knowledge_clarify_focus"] = knowledge_focus
        elif reason_norm in {"routing_fallback", "fallback_uncertain"}:
            message = tone_pick(
                "clarify:fallback_uncertain",
                [
                    "I can help right away. Tell me whether you need products, policy details, or contact info.",
                    "I can assist with products, policy, or contact details. Which one should I focus on?",
                    "Tell me your main goal and I'll route this correctly: products, policy, or contact.",
                ],
            )
            questions = ["What do you want help with right now?"]
            suggestions = [
                "Show titanium jewelry",
                "How can I contact you?",
                "What is your shipping policy?",
            ]
        elif reason_norm == "fallback_too_broad":
            message = tone_pick(
                "clarify:fallback_too_broad",
                [
                    "I can help quickly. Share one detail like piercing type, material, or SKU and I'll narrow it.",
                    "Happy to help. Tell me one preference such as type, material, or gauge and I'll refine the options.",
                    "Let's narrow this in one step. Give me piercing type, material, or SKU and I'll show the best matches.",
                ],
            )
            questions = ["Which detail should I use first: type, material, or SKU?"]
            suggestions = [
                "Show titanium labrets",
                "Show opal designs",
                "Show in-stock only",
            ]
        elif reason_norm == "fallback_gibberish":
            message = tone_pick(
                "clarify:fallback_gibberish",
                [
                    "I didn't catch that message. Can you rephrase it in a few words?",
                    "That came through unclear. Please rephrase what you need.",
                    "I couldn't parse that yet. Can you type it again with what you want help with?",
                ],
            )
            questions = ["Can you rephrase your request?"]
            suggestions = [
                "Show titanium jewelry",
                "How can I contact you?",
                "Do you have in-stock products?",
            ]

        if not message:
            message = tone_pick(
                f"clarify:{reason_norm}:default",
                [
                    "Share a little more detail so I can match the right products.",
                    "I can help faster if you add one or two more details.",
                    "Give me a bit more detail and I will narrow this down.",
                ],
            )
        if not questions:
            questions = ["Which detail should I use to continue?"]
        if not suggestions:
            if reason_norm in {"structured_no_match", "detail_no_match", "detail_request_needs_specific_product", "attribute_list_no_results"}:
                suggestions = cls._build_product_clarify_follow_ups(
                    products=products,
                    attribute_filters=attribute_filters,
                    needs_knowledge=bool(needs_knowledge),
                    limit=3,
                )
            else:
                suggestions = cls._build_knowledge_clarify_follow_ups(user_text=user_text, limit=3)

        return {
            "reason": reason_norm,
            "message": str(message or "").strip(),
            "questions": list(questions or []),
            "suggestions": list(suggestions or []),
            "extra_debug": dict(extra_debug or {}),
        }

    @classmethod
    def _build_conversion_follow_ups(
        cls,
        *,
        products: Sequence[Any],
        attribute_filters: Dict[str, str],
        user_text: str,
        needs_knowledge: bool,
        limit: int = 5,
    ) -> List[str]:
        if not bool(getattr(settings, "CHAT_CONVERSION_FOLLOW_UPS_ENABLED", True)):
            return []
        follow_ups: List[str] = []
        if "material" not in attribute_filters:
            for material in cls._top_product_attributes(products=products, key="material", limit=2):
                follow_ups.append(f"Show {material} jewelry")
        if "jewelry_type" not in attribute_filters:
            for jewelry_type in cls._top_product_attributes(products=products, key="jewelry_type", limit=2):
                follow_ups.append(f"Show {jewelry_type}")
        has_opal = any(
            str(dict(getattr(product, "attributes", {}) or {}).get("opal_color") or "").strip()
            for product in list(products or [])
        )
        if has_opal:
            follow_ups.append("Show opal colors")
        if needs_knowledge:
            follow_ups.append("How can I contact you?")
        return cls._dedupe_follow_up_questions(follow_ups, limit=limit)

    @staticmethod
    def _apply_clarify_debug(
        *,
        debug_meta: Dict[str, Any],
        reason: str,
        message: str = "",
        questions: Sequence[str] | None = None,
        suggestions: Sequence[str] | None = None,
    ) -> None:
        debug_meta["clarify_reason"] = str(reason or "").strip()
        debug_meta["clarify_message"] = str(message or "").strip()
        debug_meta["clarify_questions"] = ComponentPipeline._dedupe_follow_up_questions(list(questions or []), limit=2)
        debug_meta["clarify_suggestions"] = ComponentPipeline._dedupe_follow_up_questions(list(suggestions or []), limit=3)

    @staticmethod
    def _to_product_card(product) -> ProductCard:
        attrs = dict(product.attributes or {})
        return ProductCard(
            id=product.product_id,
            object_id=product.sku,
            sku=product.sku,
            legacy_sku=[],
            name=product.title,
            description=product.description,
            price=float(product.price),
            currency=product.currency,
            stock_status="in_stock" if product.in_stock else "out_of_stock",
            image_url=product.image_url,
            product_url=product.product_url,
            attributes=attrs,
        )

    @staticmethod
    def _to_meta(
        *,
        query_summary: str,
        source: ComponentSource,
        latency_ms: float,
        llm_calls: int,
        embedding_calls: int,
    ) -> ChatResponseMeta:
        return ChatResponseMeta(
            query_summary=str(query_summary or ""),
            latency_ms=round(float(latency_ms), 2),
            source=source.value,
            llm_calls=int(llm_calls),
            embedding_calls=int(embedding_calls),
        )

    @staticmethod
    def _components_to_map(components) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for component in components:
            raw_type = getattr(component, "type", "")
            key = str(getattr(raw_type, "value", raw_type) or "").strip().lower()
            out[key] = dict(getattr(component, "data", {}) or {})
        return out

    @staticmethod
    def _display_attribute_value(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.islower():
            return " ".join([part.capitalize() for part in text.split(" ") if part])
        return text

    @classmethod
    def _detect_attribute_list_target(cls, text: str) -> str:
        normalized = cls._normalize_text(text)
        if not normalized:
            return ""
        asks_for_list = bool(
            re.search(r"\b(what|which|list|show|available|sell|have|offer|carry)\b", normalized)
            or normalized.endswith("?")
        )
        if not asks_for_list:
            return ""
        for token, target in cls._ATTRIBUTE_LIST_TERMS.items():
            if re.search(rf"\b{re.escape(token)}\b", normalized):
                return target
        return ""

    @classmethod
    def _is_design_discovery_query(cls, *, user_text: str, attribute_filters: Dict[str, str]) -> bool:
        if dict(attribute_filters or {}):
            return False
        normalized = cls._normalize_text(user_text)
        if not normalized:
            return False
        has_design_term = any(term in normalized for term in cls._DESIGN_DISCOVERY_TERMS)
        has_discovery_phrase = bool(
            re.search(r"\b(what|which|show|have|offer|carry|available)\b", normalized)
            or normalized.endswith("?")
        )
        return bool(has_design_term and has_discovery_phrase)

    @classmethod
    def _looks_like_gibberish(cls, *, user_text: str) -> bool:
        normalized = cls._normalize_text(user_text)
        if not normalized:
            return True
        if any(hint in normalized for hint in cls._FALLBACK_VALID_HINTS):
            return False
        if re.search(r"(.)\1{4,}", normalized):
            return True
        alpha_tokens = re.findall(r"[a-z]+", normalized)
        if not alpha_tokens:
            return True
        if len(alpha_tokens) == 1:
            token = alpha_tokens[0]
            vowel_count = sum(1 for ch in token if ch in "aeiou")
            vowel_ratio = float(vowel_count) / max(1, len(token))
            if len(token) >= 8 and vowel_count <= 1:
                return True
            if len(token) >= 8 and vowel_ratio <= 0.30:
                return True
            if any(pattern in token for pattern in ("asdf", "qwer", "zxcv")):
                return True
            if len(token) >= 8 and len(set(token)) <= 3:
                return True
        return False

    @classmethod
    def _is_broad_discovery_request(
        cls,
        *,
        user_text: str,
        attribute_filters: Dict[str, str],
        sku_tokens: Sequence[str],
    ) -> bool:
        if dict(attribute_filters or {}) or list(sku_tokens or []):
            return False
        normalized = cls._normalize_text(user_text)
        if not normalized:
            return False
        broad_terms = (
            "help",
            "something",
            "anything",
            "show me",
            "what do you have",
            "what can you show",
            "recommend",
            "suggest",
            "design",
            "style",
        )
        return any(term in normalized for term in broad_terms)

    @classmethod
    def _fallback_subtype(
        cls,
        *,
        user_text: str,
        route_reason: str,
        attribute_filters: Dict[str, str],
        sku_tokens: Sequence[str],
    ) -> str:
        if cls._looks_like_gibberish(user_text=user_text):
            return "fallback_gibberish"
        if cls._is_design_discovery_query(user_text=user_text, attribute_filters=attribute_filters):
            return "fallback_too_broad"
        if cls._is_broad_discovery_request(
            user_text=user_text,
            attribute_filters=attribute_filters,
            sku_tokens=sku_tokens,
        ):
            return "fallback_too_broad"
        normalized_reason = cls._normalize_text(route_reason)
        if any(token in normalized_reason for token in ("timeout", "confidence", "invalid", "error", "unclear")):
            return "fallback_uncertain"
        return "fallback_uncertain"

    @classmethod
    def _plan_components(
        cls,
        *,
        user_text: str,
        workflow: str,
        product_count: int,
        is_detail_mode: bool,
        is_ambiguous: bool,
    ) -> List[ComponentType]:
        text = cls._normalize_text(user_text)
        workflow_norm = cls._normalize_text(workflow)

        if not text:
            return [ComponentType.ERROR]

        if is_ambiguous:
            return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]

        if workflow_norm in {"knowledge", "smalltalk"}:
            return [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]

        wants_reco = workflow_norm == "recommendation"

        components: List[ComponentType] = [ComponentType.QUERY_SUMMARY]

        if workflow_norm in {"catalog", "recommendation"} and product_count <= 0:
            return [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
        if is_detail_mode:
            components.append(ComponentType.PRODUCT_DETAIL)
        else:
            components.append(ComponentType.PRODUCT_CARDS)

        if wants_reco:
            components.append(ComponentType.RECOMMENDATIONS)

        deduped: List[ComponentType] = []
        seen = set()
        for item in components:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    @classmethod
    def _detail_request_needs_specific_product(
        cls,
        *,
        requested_fields: Sequence[str],
        attribute_filters: Dict[str, str],
        match_count: int,
        has_exact_match: bool,
    ) -> bool:
        if has_exact_match or int(match_count) <= 1:
            return False
        fields = {
            str(item or "").strip().lower()
            for item in list(requested_fields or [])
            if str(item or "").strip()
        }
        if not fields.intersection(cls._DETAIL_CLARIFY_FIELDS):
            return False
        filter_keys = {
            str(key or "").strip().lower()
            for key, value in dict(attribute_filters or {}).items()
            if str(key or "").strip() and str(value or "").strip()
        }
        if not filter_keys:
            return True
        return filter_keys == {"jewelry_type"}

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

    @classmethod
    def _top_product_attributes(
        cls,
        *,
        products: Sequence[Any],
        key: str,
        limit: int,
    ) -> List[str]:
        counts: Counter[str] = Counter()
        for product in list(products or []):
            attrs = dict(getattr(product, "attributes", {}) or {})
            if key == "material":
                raw = attrs.get("material") or getattr(product, "material", None)
            else:
                raw = attrs.get(key)
            text = cls._display_attribute_value(str(raw or ""))
            if not text:
                continue
            counts[text] += 1
        return [value for value, _count in counts.most_common(max(1, int(limit)))]

    @classmethod
    def _build_store_overview_reply(
        cls,
        *,
        products: Sequence[Any],
    ) -> str:
        jewelry_types = cls._top_product_attributes(products=products, key="jewelry_type", limit=4)
        materials = cls._top_product_attributes(products=products, key="material", limit=3)
        if jewelry_types and materials:
            return (
                f"We carry products like {', '.join(jewelry_types)} in materials such as "
                f"{', '.join(materials)}. Here are a few options to start with."
            )
        if jewelry_types:
            return f"We carry products like {', '.join(jewelry_types)}. Here are a few options to start with."
        if materials:
            return f"We carry products in materials such as {', '.join(materials)}. Here are a few options to start with."
        return "We carry a range of body jewelry and related products. Here are a few options to start with."

    @classmethod
    def _build_store_overview_follow_ups(
        cls,
        *,
        products: Sequence[Any],
        limit: int = 4,
    ) -> List[str]:
        follow_ups: List[str] = []
        for jewelry_type in cls._top_product_attributes(products=products, key="jewelry_type", limit=3):
            follow_ups.append(f"Show {jewelry_type}")
        for material in cls._top_product_attributes(products=products, key="material", limit=2):
            follow_ups.append(f"Show {material} jewelry")
        deduped: List[str] = []
        seen: set[str] = set()
        for item in follow_ups:
            key = item.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= max(1, int(limit)):
                break
        return deduped

    @classmethod
    def _build_grounded_knowledge_fallback_answer(
        cls,
        *,
        question: str,
        sources: Sequence[KnowledgeSource],
    ) -> str:
        top = list(sources or [])[:1]
        if not top:
            return "I couldn't find enough details yet. Could you clarify what you need?"
        snippet = cls._clean_knowledge_snippet_text(str(getattr(top[0], "content_snippet", "") or ""))
        if not snippet:
            return "I couldn't find enough details yet. Could you clarify what you need?"
        return cls._polish_knowledge_answer(
            answer=snippet,
            question=question,
            max_sentences=2,
            max_chars=240,
        )

    @classmethod
    def _compose_off_topic_reply(
        cls,
        *,
        user_text: str,
        pick_text: Optional[Callable[[str, Sequence[str]], str]] = None,
    ) -> str:
        choose = pick_text or (
            lambda key, variants: reply_tone.pick_variant(
                user_text=user_text,
                key=key,
                variants=variants,
            )
        )
        intro = choose(
            "off_topic:intro",
            [
                "I can only help with this store's body jewelry shopping and support.",
                "I'm focused on body jewelry products, recommendations, and store support here.",
                "I can help with body jewelry products, stock, and store policies in this chat.",
            ],
        )
        redirect = choose(
            "off_topic:redirect",
            list(cls._OFF_TOPIC_REDIRECT_OPTIONS),
        )
        return f"{intro} {redirect}"

    @staticmethod
    def _clean_knowledge_snippet_text(text: str) -> str:
        cleaned = str(text or "")
        replacements = {
            "â": "'",
            "â": "-",
            "â": "-",
            "â": " ",
            "\u2022": " ",
            "\r": " ",
            "\n": " ",
            "\t": " ",
        }
        for source, target in replacements.items():
            cleaned = cleaned.replace(source, target)
        return " ".join(cleaned.split())

    @staticmethod
    def _extract_sentences(text: str, *, limit: int) -> List[str]:
        parts = [str(item or "").strip() for item in re.split(r"(?<=[.!?])\s+", str(text or "").strip())]
        out: List[str] = []
        for part in parts:
            if not part:
                continue
            out.append(part)
            if len(out) >= max(1, int(limit)):
                break
        return out

    @classmethod
    def _looks_like_yes_no_question(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return normalized.startswith(
            (
                "do you",
                "can you",
                "can i",
                "is ",
                "are ",
                "does ",
                "did ",
                "will ",
                "would ",
            )
        )

    @classmethod
    def _polish_knowledge_answer(
        cls,
        *,
        answer: str,
        question: str,
        max_sentences: int = 2,
        max_chars: int = 240,
    ) -> str:
        text = cls._clean_knowledge_snippet_text(answer)
        text = re.sub(r"^\s*here is what i found:\s*", "", text, flags=re.IGNORECASE)
        sentences = cls._extract_sentences(text, limit=max_sentences)
        concise = " ".join(sentences).strip() if sentences else text.strip()
        if not concise:
            return ""
        if len(concise) > max(1, int(max_chars)):
            trimmed = concise[: max(1, int(max_chars))]
            if " " in trimmed:
                trimmed = trimmed.rsplit(" ", 1)[0]
            concise = trimmed.rstrip(" ,;:") + "."

        lower = concise.lower()
        if cls._looks_like_yes_no_question(question) and not lower.startswith(("yes", "no")):
            affirmative = (
                "certainly",
                "sure",
                "we welcome",
                "we offer",
                "we do",
                "available",
                "happy to",
            )
            if any(token in lower for token in affirmative):
                concise = f"Yes. {concise}"
        return concise

    @classmethod
    def _pick_store_overview_source(
        cls,
        *,
        sources: Sequence[KnowledgeSource],
    ) -> Optional[KnowledgeSource]:
        scored: List[tuple[int, KnowledgeSource]] = []
        for source in list(sources or []):
            title = cls._normalize_text(getattr(source, "title", ""))
            category = cls._normalize_text(getattr(source, "category", ""))
            snippet = cls._normalize_text(getattr(source, "content_snippet", ""))
            combined = f"{title} {category} {snippet}".strip()
            score = 0
            if any(token in combined for token in ("contact", "sales", "support", "email", "phone", "tel")):
                score += 4
            if any(token in combined for token in ("address", "showroom", "location", "in person", "bangkok")):
                score += 3
            if "company" in combined or "about" in combined:
                score += 2
            if category in {"contact", "about", "company"}:
                score += 2
            scored.append((score, source))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    @classmethod
    def _build_store_overview_knowledge_answer(
        cls,
        *,
        sources: Sequence[KnowledgeSource],
    ) -> str:
        source = cls._pick_store_overview_source(sources=sources)
        if source is None:
            return ""

        snippet = cls._clean_knowledge_snippet_text(str(getattr(source, "content_snippet", "") or ""))
        if not snippet:
            return ""

        email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", snippet)
        phone_match = re.search(r"(?:\+?\d[\d\s().-]{6,}\d)", snippet)
        address_match = re.search(
            r"address[:\s-]*(.+?)(?:\b(?:tel|phone|showroom hours|email)\b|$)",
            snippet,
            flags=re.IGNORECASE,
        )
        company_match = re.search(r"\b[A-Z][A-Za-z]+\s+Co\.,?\s*Ltd\.?\b", snippet)

        company_name = str(company_match.group(0)).strip() if company_match else "Our company"
        location_hint = ""
        if "bangkok" in snippet.lower():
            location_hint = " in Bangkok, Thailand"

        parts: List[str] = [f"{company_name} has a showroom{location_hint}."]
        if address_match:
            address = str(address_match.group(1) or "").strip(" .")
            if address:
                parts.append(f"Showroom address: {address}.")
        if email_match:
            parts.append(f"Contact email: {email_match.group(0)}.")
        if phone_match:
            phone = str(phone_match.group(0) or "").strip()
            parts.append(f"Phone: {phone}.")

        if len(parts) == 1:
            sentences = re.split(r"(?<=[.!?])\s+", snippet)
            for sentence in sentences:
                text = str(sentence or "").strip()
                if not text:
                    continue
                if text.endswith("."):
                    parts.append(text)
                else:
                    parts.append(f"{text}.")
                if len(parts) >= 3:
                    break

        return " ".join(parts).strip()

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
            value = self._normalize_text(str(raw_value or ""))
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

    @classmethod
    def _derive_legacy(
        cls,
        *,
        context: ComponentContext,
        components,
        pick_text: Optional[Callable[[str, Sequence[str]], str]] = None,
    ) -> Dict[str, Any]:
        mapped = cls._components_to_map(components)
        query_summary = str(mapped.get("query_summary", {}).get("text") or context.query_summary or "").strip()
        user_text = str(context.user_text or "").strip()
        choose = pick_text or (
            lambda key, variants: reply_tone.pick_variant(
                user_text=user_text,
                key=key,
                variants=variants,
            )
        )
        reply_text = ""
        carousel_msg = ""
        product_carousel: List[ProductCard] = []
        follow_ups: List[str] = []

        if "error" in mapped:
            reply_text = str(mapped["error"].get("message") or "I could not process this request.")
        elif "clarify" in mapped:
            reply_text = str(mapped["clarify"].get("message") or "Please share more details.")
            follow_ups.extend(list(context.debug.get("clarify_suggestions") or []))
        elif "knowledge_answer" in mapped:
            reply_text = str(mapped["knowledge_answer"].get("answer") or query_summary)
        elif "product_detail" in mapped:
            detail_products = list(context.canonical_products or [])
            product_carousel = [cls._to_product_card(item) for item in detail_products]
            reply_text = str(context.debug.get("detail_reply_text") or "").strip() or query_summary
            carousel_msg = str(context.debug.get("detail_carousel_msg") or "").strip()
            follow_ups.extend(list(context.debug.get("detail_follow_ups") or []))
        elif "product_cards" in mapped:
            if bool(context.debug.get("detail_reply_text")):
                display_products = list(context.canonical_products or [])
            else:
                display_products, _total_unique_products = product_presentation.dedupe_products_by_master_code(
                    context.canonical_products,
                    limit=product_presentation.PRODUCT_DISPLAY_LIMIT,
                )
            if bool(context.debug.get("store_overview_request")):
                reply_text = str(context.debug.get("store_overview_reply") or "").strip()
                if not reply_text:
                    reply_text = cls._build_store_overview_reply(products=display_products)
                follow_ups.extend(list(context.debug.get("store_overview_follow_ups") or []))
            elif bool(context.debug.get("detail_reply_text")):
                reply_text = str(context.debug.get("detail_reply_text") or "").strip()
                carousel_msg = str(context.debug.get("detail_carousel_msg") or "").strip()
                follow_ups.extend(list(context.debug.get("detail_follow_ups") or []))
            elif "recommendations" in mapped or bool(context.debug.get("recommendation_ranked_count")):
                reply_text = product_presentation.build_recommendation_match_reply(
                    attribute_filters=context.attribute_filters,
                    user_text=user_text,
                )
            else:
                reply_text = product_presentation.build_product_match_reply(
                    attribute_filters=context.attribute_filters,
                    user_text=user_text,
                )
            product_carousel = [cls._to_product_card(item) for item in display_products]
            if not carousel_msg:
                carousel_msg = choose(
                    f"{context.workflow}:carousel",
                    [
                        "Matching products are shown below.",
                        "These are the top matches for your request.",
                        "Here are the products that best fit your request.",
                    ],
                )
            if not bool(context.debug.get("store_overview_request")):
                follow_ups.extend(
                    cls._build_conversion_follow_ups(
                        products=display_products,
                        attribute_filters=context.attribute_filters,
                        user_text=user_text,
                        needs_knowledge=bool(context.debug.get("workflow_needs_knowledge", False)),
                        limit=5,
                    )
                )

        recommendation_items = list(mapped.get("recommendations", {}).get("items") or [])
        if recommendation_items:
            follow_ups.append(
                choose(
                    "recommendations:follow_up",
                    [
                        "Show recommendations",
                        "Show more recommendations",
                        "Recommend more like this",
                    ],
                )
            )

        if not reply_text:
            reply_text = choose(
                f"{context.workflow}:default_reply",
                [
                    "I got it. Here's what I can do next.",
                    "Understood. Here's the best next step.",
                    "Thanks for the details. Here's what I found.",
                ],
            )

        return {
            "reply_text": reply_text,
            "carousel_msg": carousel_msg,
            "product_carousel": product_carousel,
            "follow_up_questions": cls._dedupe_follow_up_questions(follow_ups, limit=5),
        }

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
                max_chars=280,
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
        answer = self._polish_knowledge_answer(answer=answer, question=question, max_sentences=2, max_chars=240)
        if store_overview_request and store_overview_answer:
            normalized_answer = self._normalize_text(answer)
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

    async def run(
        self,
        *,
        request: ChatRequest,
        conversation_id: int,
        run_id: str,
        route_decision_override: Optional[routing_policy.WorkflowDecision] = None,
        routing_selection_source: str = "",
        channel: str = "widget",
        challenge_context: Optional[Dict[str, Any]] = None,
    ) -> ComponentPipelineResult:
        started = time.perf_counter()
        text = str(request.message or "").strip()
        locale = str(request.locale or "en-US")
        challenge_payload = dict(challenge_context or {})
        challenge_mode = str(challenge_payload.get("mode") or "").strip().lower()
        challenge_target_sku = str(challenge_payload.get("target_sku") or "").strip()
        challenge_base_question = str(challenge_payload.get("base_question") or "").strip()
        challenge_reason = str(challenge_payload.get("reason") or "").strip()
        challenge_query_text = (
            challenge_base_question
            if challenge_mode == "knowledge_reconfirm" and challenge_base_question
            else text
        )
        normalized_text = self._normalize_text(text)
        normalized_challenge_query_text = self._normalize_text(challenge_query_text)
        detail = DetailQueryParser.parse(user_text=text, nlu_data={})
        conversation_state_enabled = bool(getattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False))
        state_working: Optional[Dict[str, Any]] = None
        conversation_state_filter_merge_applied = False
        if conversation_state_enabled:
            state_working = await self._load_conversation_state(conversation_id=conversation_id)
        sku_tokens = routing_policy.extract_sku_tokens(text)
        unique_sku_tokens = [token for token in dict.fromkeys([str(item).strip() for item in sku_tokens]) if token]
        if conversation_state_enabled and state_working is not None:
            debug_state_version = int(
                state_working.get("version", conversation_state.CONVERSATION_STATE_VERSION)
            )
        else:
            debug_state_version = conversation_state.CONVERSATION_STATE_VERSION
        if conversation_state_enabled and state_working is not None:
            if conversation_state.should_merge_follow_up_filters(
                user_text=text,
                current_filters=detail.attribute_filters,
                sku_token=unique_sku_tokens[0] if unique_sku_tokens else None,
            ):
                merged_filters = conversation_state.merge_filters(
                    detail.attribute_filters,
                    state_working.get("last_attribute_filters", {}),
                )
                detail = replace(detail, attribute_filters=merged_filters)
                conversation_state_filter_merge_applied = True
        tone_recent: List[Dict[str, Any]] = []
        if conversation_state_enabled and state_working is not None:
            tone_recent = reply_tone.normalize_recent(state_working.get("tone_recent"))

        route_decision = route_decision_override
        if route_decision is None:
            route_decision = routing_policy.WorkflowDecision(
                workflow="fallback",
                source=ComponentSource.ERROR,
                needs_products=False,
                needs_knowledge=False,
                needs_clarification=True,
                store_overview_request=False,
                reason="missing_workflow_override",
                confidence=0.0,
            )
        workflow = route_decision.workflow
        recommendation_requested = workflow == "recommendation"
        store_overview_request = route_decision.store_overview_request
        smalltalk_workflow = workflow == "smalltalk"
        off_topic_workflow = workflow == "off_topic"
        knowledge_workflow = workflow == "knowledge"
        fallback_workflow = workflow == "fallback"
        source = route_decision.source
        ambiguity_reason = None

        llm_calls = 0
        embedding_calls = 0
        external_call_counts: Dict[str, int] = {}
        spans: Dict[str, float] = {
            "workflow_routing_ms": 0.0,
            "db_product_lookup_ms": 0.0,
            "vector_search_ms": 0.0,
            "llm_answer_ms": 0.0,
            "response_build_ms": 0.0,
        }
        debug_meta: Dict[str, Any] = {
            "component_pipeline_enabled": True,
            "component_workflow": workflow,
            "workflow_needs_products": bool(route_decision.needs_products),
            "workflow_needs_knowledge": bool(route_decision.needs_knowledge),
            "workflow_needs_clarification": bool(route_decision.needs_clarification),
            "path_kind": "component_pipeline",
            "route_override_used": route_decision_override is not None,
            "routing_selection_source": str(routing_selection_source or "component_pipeline"),
            "image_only_filter_applied": False,
            "image_only_result_count": 0,
            "image_followup_context_used": False,
            "image_followup_context_count": 0,
            "store_overview_request": store_overview_request,
            "conversation_state_enabled": conversation_state_enabled,
            "conversation_state_filter_merge_applied": bool(conversation_state_filter_merge_applied),
            "conversation_state_loaded_version": int(debug_state_version),
            "conversation_state_written": False,
            "detail_requested_fields": list(detail.requested_fields or []),
            "challenge_mode": challenge_mode,
            "challenge_reason": challenge_reason,
            "challenge_target_sku": challenge_target_sku,
            "challenge_base_question": challenge_base_question,
        }
        tone_humanizer_enabled = bool(getattr(settings, "CHAT_TONE_HUMANIZER_ENABLED", True))
        tone_enabled_channels = {
            str(item or "").strip().lower()
            for item in str(getattr(settings, "CHAT_TONE_ENABLED_CHANNELS", "widget")).split(",")
            if str(item or "").strip()
        }
        tone_channel_allowed = not tone_enabled_channels or str(channel or "widget").strip().lower() in tone_enabled_channels
        tone_active = bool(tone_humanizer_enabled and tone_channel_allowed)
        tone_repeat_hit_count = 0
        tone_filler_stripped_count = 0
        tone_latest_key = ""
        tone_latest_variant_id = -1
        tone_latest_style = ""
        tone_latest_anti_repeat = False
        debug_meta["tone_humanizer_enabled"] = tone_humanizer_enabled
        debug_meta["tone_channel_allowed"] = tone_channel_allowed
        debug_meta["tone_active"] = tone_active

        def _tone_pick(key: str, variants: Sequence[str], *, user_text_override: Optional[str] = None) -> str:
            nonlocal tone_recent
            nonlocal tone_repeat_hit_count
            nonlocal tone_filler_stripped_count
            nonlocal tone_latest_key
            nonlocal tone_latest_variant_id
            nonlocal tone_latest_style
            nonlocal tone_latest_anti_repeat
            decision = reply_tone.compose_variant(
                user_text=str(user_text_override if user_text_override is not None else text),
                key=key,
                variants=variants,
                recent=tone_recent,
                anti_repeat_window=int(getattr(settings, "CHAT_TONE_ANTI_REPEAT_WINDOW", 4)),
                humanizer_enabled=tone_active,
                max_sentences=int(getattr(settings, "CHAT_TONE_MAX_SENTENCES", 2)),
                max_chars=int(getattr(settings, "CHAT_TONE_MAX_CHARS", 220)),
            )
            tone_recent = reply_tone.push_recent(
                tone_recent,
                decision=decision,
                max_items=conversation_state.MAX_TONE_RECENT,
            )
            tone_latest_key = str(decision.key or "")
            tone_latest_variant_id = int(decision.variant_id)
            tone_latest_style = str(decision.style or "")
            tone_latest_anti_repeat = bool(decision.anti_repeat_applied)
            if decision.anti_repeat_applied:
                tone_repeat_hit_count += 1
            if decision.filler_stripped:
                tone_filler_stripped_count += 1
            return str(decision.text or "")

        if conversation_state_enabled and state_working is not None:
            state_working = conversation_state.apply_workflow_update(
                state_working,
                workflow=workflow,
                refined_query=text,
                attribute_filters=detail.attribute_filters,
            )

        workflow_started = time.perf_counter()
        spans["workflow_routing_ms"] = (time.perf_counter() - workflow_started) * 1000.0

        query_summary = text if text else "Please provide a question."
        selected_components: List[ComponentType] = []
        canonical_products = []
        recommendations = []
        knowledge_sources: List[KnowledgeSource] = []
        knowledge_answer = ""
        result_count = 0
        product_ids: List[Any] = []
        query_embedding: Optional[List[float]] = None
        retrieval_source = source
        handled_attribute_list = False
        attribute_list_target = ""
        display_limit = product_presentation.PRODUCT_DISPLAY_LIMIT
        result_fetch_limit = max(display_limit * 6, 20)

        if challenge_mode == "inventory_reverify" and challenge_target_sku:
            verify_started = time.perf_counter()
            snapshot = await self._catalog_search.get_inventory_snapshot(challenge_target_sku)
            spans["db_product_lookup_ms"] += (time.perf_counter() - verify_started) * 1000.0
            external_call_counts["inventory_verify"] = int(external_call_counts.get("inventory_verify", 0)) + 1
            debug_meta["challenge_inventory_snapshot"] = dict(snapshot or {})
            verified_sku = str(snapshot.get("sku") or challenge_target_sku).strip()
            verified_status = str(snapshot.get("stock_status") or "").strip().lower()
            last_stock_sync_at = str(snapshot.get("last_stock_sync_at") or "").strip()
            debug_meta["inventory_verified_sku"] = verified_sku
            debug_meta["inventory_verified_status"] = verified_status
            debug_meta["inventory_last_stock_sync_at"] = last_stock_sync_at
            if bool(snapshot.get("found")) and verified_status == "in_stock":
                selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
                sync_note = f" Last stock sync: {last_stock_sync_at}." if last_stock_sync_at else ""
                knowledge_answer = f"I rechecked SKU {verified_sku}. It is currently in stock.{sync_note}"
                retrieval_source = ComponentSource.SQL
                result_count = 1
            elif bool(snapshot.get("found")):
                retrieval_source = ComponentSource.SQL
                result_count = 0
                inventory_message = f"You are right. SKU {verified_sku} is currently out of stock."
                if last_stock_sync_at:
                    inventory_message = f"{inventory_message} Last stock sync: {last_stock_sync_at}."
                featured_started = time.perf_counter()
                featured_ids = await self._load_featured_product_ids(limit=8)
                spans["db_product_lookup_ms"] += (time.perf_counter() - featured_started) * 1000.0
                if featured_ids:
                    resolved, resolver_meta = await self._field_resolver.resolve(
                        product_ids=featured_ids,
                        component_types=[ComponentType.PRODUCT_CARDS],
                        redis_cache=self._redis_cache,
                        cache_key_prefix=f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:canonical",
                    )
                    debug_meta.update(resolver_meta)
                    canonical_products = list(resolved[:4])
                if canonical_products:
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                    debug_meta["detail_reply_text"] = inventory_message
                    debug_meta["detail_carousel_msg"] = "Here are similar options that are available now."
                    debug_meta["detail_follow_ups"] = ["Show alternatives", "Show in-stock options"]
                    result_count = len(canonical_products)
                else:
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
                    knowledge_answer = inventory_message
            else:
                ambiguity_reason = "challenge_target_not_found"
                selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                retrieval_source = ComponentSource.ERROR
                result_count = 0
        elif smalltalk_workflow:
            selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            knowledge_answer = _tone_pick(
                "smalltalk:redirect",
                [
                    "Hi. Tell me what body jewelry you need, like type, material, gauge, or SKU.",
                    "Happy to help. Share the product type, material, gauge, or SKU and I will narrow it down.",
                    "Sure, tell me what you're looking for and I can find options by type, material, or SKU.",
                ],
            )
            retrieval_source = ComponentSource.TOOL
        elif off_topic_workflow:
            selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            knowledge_answer = self._compose_off_topic_reply(
                user_text=text,
                pick_text=lambda key, variants: _tone_pick(key, variants),
            )
            retrieval_source = ComponentSource.ERROR
            result_count = 0
        elif store_overview_request:
            featured_started = time.perf_counter()
            product_ids = await self._load_featured_product_ids(limit=result_fetch_limit)
            spans["db_product_lookup_ms"] += (time.perf_counter() - featured_started) * 1000.0
            result_count = len(product_ids)
            retrieval_source = ComponentSource.SQL
            debug_meta["store_overview_candidate_count"] = int(result_count)
        # Generic image follow-up can reuse latest conversation product context.
        if (
            challenge_mode != "inventory_reverify"
            and not smalltalk_workflow
            and not ambiguity_reason
            and bool(detail.wants_image)
            and not unique_sku_tokens
            and not bool(detail.attribute_filters)
        ):
            context_started = time.perf_counter()
            product_ids = await self._load_recent_product_ids_for_image_followup(
                conversation_id=conversation_id,
                max_messages=8,
                max_ids=20,
            )
            spans["db_product_lookup_ms"] += (time.perf_counter() - context_started) * 1000.0
            if product_ids:
                result_count = len(product_ids)
                retrieval_source = ComponentSource.SQL
                debug_meta["image_followup_context_used"] = True
                debug_meta["image_followup_context_count"] = int(result_count)
            else:
                ambiguity_reason = "image_request_missing_context"

        if (
            challenge_mode != "inventory_reverify"
            and workflow in {"catalog", "recommendation"}
            and not ambiguity_reason
            and not store_overview_request
        ):
            attribute_list_target = self._detect_attribute_list_target(text)
            if (
                attribute_list_target
                and not unique_sku_tokens
                and not bool(detail.wants_image)
            ):
                values = await self._load_distinct_attribute_values(
                    target=attribute_list_target,
                    attribute_filters=detail.attribute_filters,
                    limit=20,
                )
                debug_meta["attribute_list_target"] = attribute_list_target
                debug_meta["attribute_list_values_count"] = int(len(values))
                if values:
                    handled_attribute_list = True
                    result_count = len(values)
                    retrieval_source = ComponentSource.SQL
                    label_map = {
                        "material": "materials",
                        "color": "colors",
                        "gauge": "gauges",
                        "threading": "threading options",
                        "jewelry_type": "jewelry types",
                    }
                    label = label_map.get(attribute_list_target, f"{attribute_list_target} options")
                    preview = ", ".join([str(item) for item in values[:12]])
                    knowledge_answer = f"We currently sell these {label}: {preview}."
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
                    debug_meta["attribute_list_values"] = values
                else:
                    ambiguity_reason = "attribute_list_no_results"

        if (
            challenge_mode != "inventory_reverify"
            and workflow in {"catalog", "recommendation"}
            and not ambiguity_reason
            and not handled_attribute_list
        ):
            if product_ids:
                debug_meta["query_id_cache_hit"] = False
                debug_meta["structured_read_mode"] = "history"
                debug_meta["projection_hit"] = False
            else:
                query_cache_key: Optional[str] = None
                sql_first_enabled = bool(getattr(settings, "CHAT_SQL_FIRST_ENABLED", True))
                debug_meta["semantic_primary_used"] = False
                if not sql_first_enabled:
                    debug_meta["semantic_primary_skipped"] = True

                if product_ids:
                    query_cache_key = None
                else:
                    read_mode = "projection" if bool(getattr(settings, "CHAT_PROJECTION_READ_ENABLED", False)) else "eav"
                    query_cache_key = stable_cache_key(
                        f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:query_ids",
                        {
                            "q": normalized_text,
                            "locale": locale.lower(),
                            "sku": unique_sku_tokens[0].lower() if unique_sku_tokens else "",
                            "sku_list": [item.lower() for item in unique_sku_tokens[:5]],
                            "filters": detail.attribute_filters,
                            "catalog_version": str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
                            "read_mode": read_mode,
                            "presentation": "master_dedupe_v1",
                            "fetch_limit": result_fetch_limit,
                        },
                    )
                    cached_ids_payload = await self._redis_cache.get_json(query_cache_key)
                    if isinstance(cached_ids_payload, dict) and isinstance(cached_ids_payload.get("product_ids"), list):
                        product_ids = list(cached_ids_payload.get("product_ids") or [])
                        cached_source = str(cached_ids_payload.get("source") or "sql")
                        retrieval_source = ComponentSource(cached_source) if cached_source in {e.value for e in ComponentSource} else ComponentSource.SQL
                        result_count = int(cached_ids_payload.get("result_count") or 0)
                        debug_meta["query_id_cache_hit"] = True
                        debug_meta["match_tier"] = result_policy.classify_match_tier(
                            structured_found=retrieval_source == ComponentSource.SQL and bool(product_ids),
                            semantic_found=retrieval_source == ComponentSource.VECTOR and bool(product_ids),
                        )
                    else:
                        debug_meta["query_id_cache_hit"] = False
                        structured_started = time.perf_counter()
                        structured_result, structured_meta = await self._catalog_search.structured_search(
                            sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                            attribute_filters=detail.attribute_filters,
                            limit=result_fetch_limit,
                            candidate_cap=int(getattr(settings, "CHAT_STRUCTURED_CANDIDATE_CAP", 300)),
                            catalog_version=str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
                            return_ids_only=True,
                        )
                        spans["db_product_lookup_ms"] += (time.perf_counter() - structured_started) * 1000.0
                        product_ids = list(structured_result.product_ids or [])
                        retrieval_source = ComponentSource.SQL
                        debug_meta["structured_read_mode"] = structured_meta.get("structured_read_mode")
                        debug_meta["projection_hit"] = structured_meta.get("projection_hit")

                        opal_retry_filters: Optional[Dict[str, str]] = None
                        if not product_ids:
                            color_value = str(detail.attribute_filters.get("color") or "").strip().lower()
                            if color_value == "opal" and "opal_color" not in detail.attribute_filters:
                                opal_retry_filters = dict(detail.attribute_filters)
                                opal_retry_filters.pop("color", None)
                                opal_retry_filters["opal_color"] = "opal"

                        if opal_retry_filters:
                            retry_started = time.perf_counter()
                            retry_result, retry_meta = await self._catalog_search.structured_search(
                                sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                                attribute_filters=opal_retry_filters,
                                limit=result_fetch_limit,
                                candidate_cap=int(getattr(settings, "CHAT_STRUCTURED_CANDIDATE_CAP", 300)),
                                catalog_version=str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
                                return_ids_only=True,
                            )
                            spans["db_product_lookup_ms"] += (time.perf_counter() - retry_started) * 1000.0
                            product_ids = list(retry_result.product_ids or [])
                            debug_meta["opal_color_retry_applied"] = True
                            debug_meta["opal_color_retry_found"] = bool(product_ids)
                            debug_meta["opal_color_retry_filters"] = dict(opal_retry_filters)
                            if product_ids:
                                detail = replace(detail, attribute_filters=opal_retry_filters)
                                debug_meta["structured_read_mode"] = retry_meta.get("structured_read_mode")
                                debug_meta["projection_hit"] = retry_meta.get("projection_hit")
                                query_cache_key = stable_cache_key(
                                    f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:query_ids",
                                    {
                                        "q": normalized_text,
                                        "locale": locale.lower(),
                                        "sku": unique_sku_tokens[0].lower() if unique_sku_tokens else "",
                                        "sku_list": [item.lower() for item in unique_sku_tokens[:5]],
                                        "filters": detail.attribute_filters,
                                        "catalog_version": str(getattr(settings, "CHAT_CATALOG_VERSION", "v1")),
                                        "read_mode": read_mode,
                                        "presentation": "master_dedupe_v1",
                                        "fetch_limit": result_fetch_limit,
                                    },
                                )
                        else:
                            debug_meta["opal_color_retry_applied"] = False

                        semantic_decision = result_policy.semantic_fallback_decision(
                            workflow=workflow,
                            attribute_filters=detail.attribute_filters,
                            sku_tokens=unique_sku_tokens,
                            detail_mode=bool(detail.is_detail_request),
                            store_overview_request=store_overview_request,
                        )
                        debug_meta["semantic_fallback_allowed"] = bool(semantic_decision.allow)
                        debug_meta["semantic_fallback_reason"] = semantic_decision.reason

                        if product_ids:
                            if len(product_ids) >= int(result_fetch_limit):
                                result_count = await self._catalog_search.structured_count(
                                    sku_token=unique_sku_tokens[0] if unique_sku_tokens else "",
                                    attribute_filters=detail.attribute_filters,
                                )
                                debug_meta["structured_count_skipped"] = False
                            else:
                                result_count = len(product_ids)
                                debug_meta["structured_count_skipped"] = True
                            debug_meta["match_tier"] = result_policy.classify_match_tier(
                                structured_found=True,
                                semantic_found=False,
                            )
                        elif (
                            semantic_decision.allow
                            and int(getattr(settings, "CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST", 1)) > 0
                            and not unique_sku_tokens
                        ):
                            try:
                                embed_started = time.perf_counter()
                                embedding = await llm_service.generate_embedding(text)
                                spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                                query_embedding = list(embedding or [])
                                embedding_calls += 1
                                external_call_counts["embedding_query"] = (
                                    int(external_call_counts.get("embedding_query", 0)) + 1
                                )
                                vector_started = time.perf_counter()
                                vector_result = await self._catalog_search.smart_search(
                                    query_embedding=embedding,
                                    candidates=sku_tokens or [text],
                                    limit=result_fetch_limit,
                                )
                                spans["vector_search_ms"] += (time.perf_counter() - vector_started) * 1000.0
                                product_ids = list(vector_result.product_ids or [str(card.id) for card in vector_result.cards])
                                result_count = len(product_ids)
                                retrieval_source = ComponentSource.VECTOR if product_ids else ComponentSource.SQL
                                debug_meta["match_tier"] = result_policy.classify_match_tier(
                                    structured_found=False,
                                    semantic_found=bool(product_ids),
                                )
                                if not product_ids:
                                    ambiguity_reason = "structured_no_match"
                            except Exception as exc:
                                debug_meta["component_vector_fallback_error"] = str(exc)
                                debug_meta["component_vector_fallback_skipped"] = True
                                product_ids = []
                                result_count = 0
                                retrieval_source = ComponentSource.SQL
                                ambiguity_reason = "structured_no_match"
                                debug_meta["match_tier"] = result_policy.classify_match_tier(
                                    structured_found=False,
                                    semantic_found=False,
                                )
                        else:
                            debug_meta["component_vector_fallback_skipped"] = True
                            product_ids = []
                            result_count = 0
                            retrieval_source = ComponentSource.SQL
                            ambiguity_reason = "structured_no_match"
                            debug_meta["match_tier"] = result_policy.classify_match_tier(
                                structured_found=False,
                                semantic_found=False,
                            )

                        if query_cache_key:
                            await self._redis_cache.set_json(
                                query_cache_key,
                                {
                                    "product_ids": [str(item) for item in product_ids],
                                    "source": retrieval_source.value,
                                    "result_count": result_count,
                                },
                                ttl_seconds=300,
                            )

            selected_components = self._plan_components(
                user_text=text,
                workflow=workflow,
                product_count=len(product_ids),
                is_detail_mode=bool(detail.is_detail_request),
                is_ambiguous=bool(ambiguity_reason),
            )
            if (
                recommendation_requested
                and product_ids
                and ComponentType.RECOMMENDATIONS not in selected_components
            ):
                selected_components.append(ComponentType.RECOMMENDATIONS)

            resolver_started = time.perf_counter()
            canonical_products, resolver_meta = await self._field_resolver.resolve(
                product_ids=product_ids,
                component_types=selected_components,
                redis_cache=self._redis_cache,
            )
            spans["db_product_lookup_ms"] += (time.perf_counter() - resolver_started) * 1000.0
            debug_meta.update(resolver_meta)
            result_count = max(result_count, len(canonical_products))

            if store_overview_request and canonical_products:
                debug_meta["store_overview_reply"] = self._build_store_overview_reply(products=canonical_products)
                debug_meta["store_overview_follow_ups"] = self._build_store_overview_follow_ups(
                    products=canonical_products,
                    limit=4,
                )

            if detail.wants_image and not bool(detail.is_detail_request):
                debug_meta["image_only_filter_applied"] = True
                canonical_products = [
                    item
                    for item in canonical_products
                    if str(getattr(item, "image_url", "") or "").strip()
                ]
                result_count = len(canonical_products)
                debug_meta["image_only_result_count"] = int(result_count)
                if result_count <= 0:
                    ambiguity_reason = "image_only_no_results"
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    recommendations = []

            if detail.is_detail_request and canonical_products and not recommendation_requested:
                candidate_cards = [self._to_product_card(item) for item in canonical_products]
                resolution = ProductDetailResolver().resolve_detail_request(
                    candidate_cards=candidate_cards,
                    distance_by_id={str(card.id): 0.0 for card in candidate_cards},
                    requested_fields=detail.requested_fields,
                    attribute_filters=detail.attribute_filters,
                    sku_token=unique_sku_tokens[0] if unique_sku_tokens else None,
                    nlu_product_code=unique_sku_tokens[0] if unique_sku_tokens else None,
                    max_matches=int(getattr(settings, "CHAT_DETAIL_MAX_MATCHES", 3)),
                    min_confidence=float(getattr(settings, "CHAT_DETAIL_MIN_CONFIDENCE", 0.55)),
                )
                debug_meta["detail_match_count"] = len(resolution.matches)
                debug_meta["detail_has_exact_match"] = resolution.has_exact_match
                if self._detail_request_needs_specific_product(
                    requested_fields=resolution.requested_fields,
                    attribute_filters=resolution.attribute_filters,
                    match_count=len(resolution.matches),
                    has_exact_match=resolution.has_exact_match,
                ):
                    ambiguity_reason = "detail_request_needs_specific_product"
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    canonical_products = []
                    recommendations = []
                else:
                    detail_payload = DetailResponseBuilder().build_detail_reply(
                        matches=resolution.matches,
                        requested_fields=resolution.requested_fields,
                        attribute_filters=resolution.attribute_filters,
                        missing_fields_by_product=resolution.missing_fields_by_product,
                        wants_image=detail.wants_image,
                        max_matches=int(getattr(settings, "CHAT_DETAIL_MAX_MATCHES", 3)),
                    )
                    debug_meta["detail_card_policy_reason"] = detail_payload.card_policy_reason
                    debug_meta["detail_reply_text"] = detail_payload.reply_text
                    debug_meta["detail_carousel_msg"] = detail_payload.carousel_msg
                    debug_meta["detail_follow_ups"] = list(detail_payload.follow_up_questions or [])
                    detail_by_id = {str(item.product_id): item for item in canonical_products}
                    canonical_products = [
                        detail_by_id[str(card.id)]
                        for card in list(detail_payload.product_carousel or [])
                        if str(card.id) in detail_by_id
                    ]
                    result_count = len(canonical_products)
                    if canonical_products:
                        if str(detail_payload.card_policy_reason or "") == "image_master_grouped":
                            selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                        else:
                            selected_components = (
                                [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_DETAIL]
                                if len(canonical_products) == 1
                                else [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS]
                            )
                    else:
                        ambiguity_reason = "detail_no_match"
                        selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                        recommendations = []
                if ambiguity_reason == "detail_request_needs_specific_product":
                    result_count = 0
                elif not canonical_products and ambiguity_reason != "detail_no_match":
                    ambiguity_reason = "detail_no_match"
                    selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                    recommendations = []

            if recommendation_requested and canonical_products:
                anchor_products = list(canonical_products[:3])
                anchor_ids = [item.product_id for item in anchor_products]
                recommendation_mode = self._recommendation_service.detect_mode(user_text=text)
                debug_meta["recommendation_mode_requested"] = recommendation_mode
                expansion_product_ids: List[Any] = []
                recommendation_distance_by_id: Dict[str, float] = {}

                if recommendation_mode == "complementary_items":
                    complementary_profile = self._recommendation_service.build_complementary_profile(
                        anchor_products=anchor_products,
                        attribute_filters=detail.attribute_filters,
                    )
                    if complementary_profile is not None:
                        debug_meta["recommendation_complementary_label"] = complementary_profile.label
                        debug_meta["recommendation_complementary_query"] = complementary_profile.search_query
                        try:
                            embed_started = time.perf_counter()
                            complementary_embedding = await llm_service.generate_embedding(
                                complementary_profile.search_query
                            )
                            spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                            embedding_calls += 1
                            external_call_counts["embedding_recommendation_complementary"] = (
                                int(external_call_counts.get("embedding_recommendation_complementary", 0)) + 1
                            )
                            vector_started = time.perf_counter()
                            complementary_result = await self._catalog_search.vector_search(
                                query_embedding=list(complementary_embedding or []),
                                limit=result_fetch_limit,
                                candidate_limit=max(result_fetch_limit * 4, 36),
                            )
                            spans["vector_search_ms"] += (time.perf_counter() - vector_started) * 1000.0
                            expansion_product_ids = [str(card.id) for card in list(complementary_result.cards or [])]
                            recommendation_distance_by_id.update(
                                {
                                    str(key): float(value)
                                    for key, value in dict(complementary_result.distance_by_id or {}).items()
                                }
                            )
                            debug_meta["recommendation_expand_source"] = "complementary_mapping"
                            debug_meta["recommendation_used_anchor_embedding"] = False
                            debug_meta["recommendation_used_query_embedding"] = True
                            debug_meta["recommendation_expand_count"] = int(len(expansion_product_ids))
                        except Exception as exc:
                            debug_meta["recommendation_complementary_expand_error"] = str(exc)
                    else:
                        debug_meta["recommendation_complementary_profile_missing"] = True

                if not expansion_product_ids:
                    reco_started = time.perf_counter()
                    expansion = await self._recommendation_service.expand_card_candidates(
                        anchor_product_ids=anchor_ids,
                        query_embedding=query_embedding,
                        limit=result_fetch_limit,
                    )
                    spans["vector_search_ms"] += (time.perf_counter() - reco_started) * 1000.0
                    debug_meta["recommendation_expand_source"] = expansion.source
                    debug_meta["recommendation_used_anchor_embedding"] = expansion.used_anchor_embedding
                    debug_meta["recommendation_used_query_embedding"] = expansion.used_query_embedding
                    debug_meta["recommendation_expand_count"] = int(len(expansion.product_ids))
                    expansion_product_ids = list(expansion.product_ids or [])
                    recommendation_distance_by_id.update(
                        {str(key): float(value) for key, value in dict(expansion.distance_by_id or {}).items()}
                    )

                if expansion_product_ids:
                    existing_ids = {str(item) for item in list(product_ids or [])}
                    extra_ids = [item for item in expansion_product_ids if str(item) not in existing_ids]
                    if extra_ids:
                        merged_ids = list(product_ids) + extra_ids
                        resolver_started = time.perf_counter()
                        canonical_products, resolver_meta = await self._field_resolver.resolve(
                            product_ids=merged_ids,
                            component_types=selected_components,
                            redis_cache=self._redis_cache,
                        )
                        spans["db_product_lookup_ms"] += (time.perf_counter() - resolver_started) * 1000.0
                        debug_meta.update(resolver_meta)
                        product_ids = merged_ids
                        debug_meta["recommendation_expand_added_ids"] = int(len(extra_ids))

                ranked = self._recommendation_service.rank_canonical_products(
                    candidates=canonical_products,
                    attribute_filters=detail.attribute_filters,
                    user_text=text,
                    distance_by_id=recommendation_distance_by_id,
                    anchor_products=anchor_products,
                    limit=result_fetch_limit,
                    exclude_product_ids=anchor_ids
                    if (unique_sku_tokens or recommendation_mode == "complementary_items")
                    else None,
                )
                debug_meta.update(ranked.meta)
                if ranked.items:
                    canonical_products = list(ranked.items)
                recommendations = list(canonical_products[:5])

            if bool(detail.is_detail_request):
                display_products = list(canonical_products)
                total_unique_products = len(display_products)
            else:
                display_products, total_unique_products = product_presentation.dedupe_products_by_master_code(
                    canonical_products,
                    limit=display_limit,
                )
            debug_meta["raw_product_row_count"] = int(len(canonical_products))
            debug_meta["product_unique_master_count"] = int(total_unique_products)
            debug_meta["product_display_count"] = int(len(display_products))
            debug_meta["product_overflow_available"] = bool(total_unique_products > len(display_products))
            canonical_products = list(display_products)
            result_count = max(int(result_count or 0), int(total_unique_products))
            if recommendation_requested and not recommendations:
                recommendations = list(canonical_products[:5])
        elif (
            workflow in {"catalog", "recommendation"}
            and not handled_attribute_list
            and challenge_mode != "inventory_reverify"
        ):
            selected_components = self._plan_components(
                user_text=text,
                workflow=workflow,
                product_count=0,
                is_detail_mode=bool(detail.is_detail_request),
                is_ambiguous=True,
            )
        elif knowledge_workflow:
            selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
            knowledge_error_message = ""
            knowledge_query = challenge_query_text if challenge_query_text else text
            knowledge_query_normalized = normalized_challenge_query_text if challenge_query_text else normalized_text
            knowledge_is_high_risk = self._is_high_risk_knowledge_request(text=knowledge_query)
            min_knowledge_relevance = float(getattr(settings, "CHAT_KNOWLEDGE_MIN_RELEVANCE", 0.55))
            if int(getattr(settings, "CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST", 1)) > 0:
                try:
                    embed_started = time.perf_counter()
                    embedding = await llm_service.generate_embedding(knowledge_query)
                    spans["vector_search_ms"] += (time.perf_counter() - embed_started) * 1000.0
                    embedding_calls += 1
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

            knowledge_sources_weak = self._knowledge_sources_are_weak(
                sources=knowledge_sources,
                min_relevance=min_knowledge_relevance,
            )
            debug_meta["knowledge_sources_weak"] = knowledge_sources_weak
            debug_meta["knowledge_is_high_risk"] = knowledge_is_high_risk
            debug_meta["knowledge_min_relevance"] = min_knowledge_relevance
            skip_knowledge_answer = bool(
                knowledge_is_high_risk and (bool(knowledge_error_message) or knowledge_sources_weak)
            )
            debug_meta["knowledge_answer_skipped"] = skip_knowledge_answer

            if not skip_knowledge_answer and not knowledge_error_message:
                llm_cache_key = stable_cache_key(
                    f"{getattr(settings, 'CHAT_REDIS_KEY_PREFIX', 'chat:components')}:knowledge_answer",
                    {
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
                    )
                    spans["llm_answer_ms"] += (time.perf_counter() - llm_started) * 1000.0
                    if not from_cache:
                        llm_calls += 1
                        external_call_counts["llm_answer"] = int(external_call_counts.get("llm_answer", 0)) + 1
                except Exception as exc:
                    debug_meta["component_knowledge_answer_error"] = str(exc)
                    knowledge_error_message = self._KNOWLEDGE_UNAVAILABLE_MESSAGE

            if knowledge_error_message and knowledge_is_high_risk:
                ambiguity_reason = "knowledge_unavailable"
                selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                retrieval_source = ComponentSource.KNOWLEDGE
                result_count = 0
                debug_meta["component_knowledge_fail_soft"] = True
            elif knowledge_sources_weak and knowledge_is_high_risk:
                ambiguity_reason = "knowledge_needs_clarification"
                selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
                retrieval_source = ComponentSource.KNOWLEDGE
                result_count = 0
                debug_meta["component_knowledge_needs_clarification"] = True
            elif knowledge_error_message:
                selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.ERROR]
                retrieval_source = ComponentSource.ERROR
                result_count = 0
                debug_meta["component_knowledge_fail_soft"] = True
            else:
                retrieval_source = ComponentSource.KNOWLEDGE
                result_count = len(knowledge_sources)
        elif fallback_workflow:
            if challenge_mode == "needs_target_clarification":
                ambiguity_reason = "challenge_target_clarification"
            else:
                ambiguity_reason = ambiguity_reason or self._fallback_subtype(
                    user_text=text,
                    route_reason=str(route_decision.reason or ""),
                    attribute_filters=dict(detail.attribute_filters or {}),
                    sku_tokens=unique_sku_tokens,
                )
            selected_components = [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]
            retrieval_source = ComponentSource.ERROR
            result_count = 0

        if ComponentType.CLARIFY in selected_components:
            clarify_policy = self._build_clarify_policy(
                reason=str(ambiguity_reason or "missing_details"),
                user_text=text,
                tone_pick=_tone_pick,
                products=canonical_products,
                attribute_filters=dict(detail.attribute_filters or {}),
                needs_knowledge=bool(route_decision.needs_knowledge),
                requested_fields=list(detail.requested_fields or []),
            )
            self._apply_clarify_debug(
                debug_meta=debug_meta,
                reason=str(clarify_policy.get("reason") or "missing_details"),
                message=str(clarify_policy.get("message") or ""),
                questions=list(clarify_policy.get("questions") or []),
                suggestions=list(clarify_policy.get("suggestions") or []),
            )
            debug_meta.update(dict(clarify_policy.get("extra_debug") or {}))

        context = ComponentContext(
            user_text=text,
            locale=locale,
            workflow=workflow,
            query_summary=query_summary,
            source=retrieval_source,
            selected_components=selected_components,
            canonical_products=canonical_products,
            recommendations=recommendations,
            knowledge_sources=knowledge_sources,
            knowledge_answer=knowledge_answer,
            result_count=result_count,
            attribute_filters=dict(detail.attribute_filters or {}),
            sku_tokens=list(sku_tokens),
            ambiguity_reason=ambiguity_reason,
            error_message=knowledge_error_message if knowledge_workflow else None,
            debug=debug_meta,
        )

        build_started = time.perf_counter()
        components = await ComponentRegistry.build_components(
            component_types=selected_components,
            context=context,
        )
        spans["response_build_ms"] += (time.perf_counter() - build_started) * 1000.0

        legacy = self._derive_legacy(
            context=context,
            components=components,
            pick_text=lambda key, variants: _tone_pick(key, variants),
        )
        total_ms = (time.perf_counter() - started) * 1000.0
        meta = self._to_meta(
            query_summary=query_summary,
            source=retrieval_source,
            latency_ms=total_ms,
            llm_calls=llm_calls,
            embedding_calls=embedding_calls,
        )
        response = ChatResponse(
            conversation_id=conversation_id,
            reply_text=str(legacy["reply_text"]),
            carousel_msg=str(legacy["carousel_msg"] or ""),
            product_carousel=list(legacy["product_carousel"] or []),
            follow_up_questions=list(legacy["follow_up_questions"] or []),
            routing=route_decision.to_public_routing(
                execution_mode="component",
                selection_source=str(routing_selection_source or "component_pipeline"),
            ),
            sources=knowledge_sources,
            debug={},
            components=components,
            meta=meta,
        )
        conversation_state_payload: Optional[Dict[str, Any]] = None
        if conversation_state_enabled and state_working is not None:
            state_product_ids = conversation_state.product_ids_from_cards(response.product_carousel)
            state_product_skus = conversation_state.product_skus_from_cards(response.product_carousel)
            inventory_claim = {
                "sku": str(debug_meta.get("inventory_verified_sku") or ""),
                "stock_status": str(debug_meta.get("inventory_verified_status") or ""),
                "last_stock_sync_at": str(debug_meta.get("inventory_last_stock_sync_at") or ""),
            }
            if not inventory_claim["sku"] and list(response.product_carousel or []):
                first_card = response.product_carousel[0]
                inventory_claim["sku"] = str(getattr(first_card, "sku", "") or "")
                inventory_claim["stock_status"] = str(getattr(first_card, "stock_status", "") or "")
            state_working = conversation_state.apply_retrieval_update(
                state_working,
                product_ids=state_product_ids,
                product_skus=state_product_skus,
                route=workflow,
            )
            state_working = conversation_state.apply_response_update(
                state_working,
                requested_fields=detail.requested_fields,
                currency=(
                    str(response.product_carousel[0].currency or "")
                    if list(response.product_carousel or [])
                    else ""
                ),
                route=workflow,
                product_ids=state_product_ids,
                product_skus=state_product_skus,
                answer_source_ids=[str(source.source_id or "") for source in knowledge_sources if str(source.source_id or "").strip()],
                inventory_claim=inventory_claim,
                tone_recent=tone_recent,
            )
            conversation_state_payload = dict(state_working)
            debug_meta["conversation_state_written"] = True

        debug_meta.update(
            {
                "component_plan": [item.value for item in selected_components],
                "component_count": len(components),
                "embedding_count": embedding_calls,
                "llm_call_count": llm_calls,
                "component_source": retrieval_source.value,
                "tone_style": tone_latest_style,
                "tone_key": tone_latest_key,
                "tone_variant_id": tone_latest_variant_id if tone_latest_variant_id >= 0 else None,
                "tone_anti_repeat_applied": bool(tone_latest_anti_repeat),
                "tone_repeat_hit": int(tone_repeat_hit_count),
                "tone_filler_stripped": int(tone_filler_stripped_count),
            }
        )
        return ComponentPipelineResult(
            response=response,
            detail_mode_triggered=bool(detail.is_detail_request),
            llm_calls=llm_calls,
            embedding_calls=embedding_calls,
            external_call_counts=external_call_counts,
            spans=spans,
            debug=debug_meta,
            conversation_state=conversation_state_payload,
        )
