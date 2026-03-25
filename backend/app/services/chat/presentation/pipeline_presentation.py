from __future__ import annotations

from collections import Counter
import re
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.core.config import settings
from app.schemas.chat import (
    ChatComponent,
    ChatComponentType,
    ChatResponse,
    ChatResponseMeta,
    KnowledgeSource,
    ProductCard,
)
from app.services.chat.runtime import conversation_state
from app.services.chat.presentation import component_contract, product_presentation, reply_tone
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.pipeline_runtime.state import (
    ComponentPipelineResult,
    PipelineWorkflowState,
)
from app.services.chat.components.registry import ComponentRegistry
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.text_normalization import normalize_user_text



class PipelinePresentationMixin:
    @staticmethod
    def _combine_mixed_assistant_text(*, product_text: str, knowledge_text: str) -> str:
            product = str(product_text or "").strip()
            knowledge = str(knowledge_text or "").strip()
            if not product:
                return knowledge
            if not knowledge:
                return product
            if knowledge.lower() in product.lower():
                return product
            if product[-1:] not in {".", "!", "?"}:
                product = f"{product}."
            return f"{product} {knowledge}"

    @staticmethod
    def _card_identifier(card: Any) -> str:
            card_id = getattr(card, "id", None)
            if card_id is None:
                card_id = getattr(card, "product_id", None)
            return str(card_id or "")

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
            normalized = normalize_user_text(user_text)
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
            normalized = normalize_user_text(user_text)
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
            clarify_focus: str = "",
        ) -> Dict[str, Any]:
            reason_norm = str(reason or "missing_details").strip() or "missing_details"
            message = ""
            questions: List[str] = []
            suggestions: List[str] = []
            extra_debug: Dict[str, Any] = {}

            if reason_norm == "attribute_list_no_results":
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
            elif reason_norm == "semantic_concept_unclear":
                focus = str(clarify_focus or "").strip().lower()
                if focus == "sterilization_meaning":
                    message = tone_pick(
                        "clarify:semantic_concept_unclear:sterilization",
                        [
                            "Do you mean pre-sterilized jewelry, surgical steel jewelry, or sterile-packed products?",
                            "When you say sterilization, do you mean pre-sterilized jewelry, surgical steel, or sterile-packed items?",
                            "To narrow this down, do you mean pre-sterilized jewelry, surgical steel jewelry, or sterile-packed products?",
                        ],
                    )
                    questions = ["Which sterilization-related option do you mean?"]
                    suggestions = [
                        "Show surgical steel jewelry",
                        "Show pre-sterilized jewelry",
                        "Show sterile-packed products",
                    ]
                else:
                    message = tone_pick(
                        "clarify:semantic_concept_unclear",
                        [
                            "I need one detail to interpret that product concept correctly. Can you be a bit more specific?",
                            "That concept can mean a few different things. Tell me which type you want and I'll narrow it down.",
                            "I can help, but I need one more detail about what you mean before I show products.",
                        ],
                    )
                    questions = ["Which product concept should I focus on?"]
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
            elif reason_norm == "pagination_exhausted":
                message = tone_pick(
                    "clarify:pagination_exhausted",
                    [
                        "That was the last set of matching products I found. Try a different material, gauge, or jewelry type.",
                        "I reached the end of the matching products. If you want more, change one filter like material or gauge.",
                        "That was the final page of matches. Adjust your search and I can find more options.",
                    ],
                )
                questions = ["Which filter should I change next?"]
                suggestions = [
                    "Show titanium jewelry",
                    "Show labret options",
                    "What other materials do you have?",
                ]
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
            result_count: int,
            display_count: int,
            display_offset: int = 0,
            limit: int = 5,
            debug_meta: Optional[Dict[str, Any]] = None,
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
            follow_ups.extend(
                cls._build_show_more_follow_up(
                    products=products,
                    attribute_filters=attribute_filters,
                    result_count=result_count,
                    display_count=display_count,
                    display_offset=int(display_offset or 0),
                )
            )
            if follow_ups and isinstance(debug_meta, dict):
                quick_reply_actions = dict(debug_meta.get("quick_reply_actions") or {})
                for label in follow_ups:
                    label_key = str(label or "").strip().lower()
                    if not label_key.startswith("show more"):
                        continue
                    quick_reply_actions[label_key] = {
                        "action": "catalog_pagination",
                        "payload": {
                            "kind": "catalog_pagination",
                            "label": str(label or "").strip(),
                        },
                    }
                if quick_reply_actions:
                    debug_meta["quick_reply_actions"] = quick_reply_actions
            if needs_knowledge:
                follow_ups.append("How can I contact you?")
            return cls._dedupe_follow_up_questions(follow_ups, limit=limit)

    @classmethod
    def _build_show_more_follow_up(
            cls,
            *,
            products: Sequence[Any],
            attribute_filters: Dict[str, str],
            result_count: int,
            display_count: int,
            display_offset: int = 0,
        ) -> List[str]:
            total_results = max(0, int(result_count or 0))
            shown_results = max(0, int(display_count or 0))
            shown_offset = max(0, int(display_offset or 0))
            if total_results <= shown_results + shown_offset:
                return []

            def _label_from_key(key: str) -> str:
                raw = str((attribute_filters or {}).get(key) or "").strip()
                if raw:
                    return cls._display_attribute_value(raw)
                values = cls._top_product_attributes(products=products, key=key, limit=1)
                return values[0] if values else ""

            material = _label_from_key("material")
            if material:
                return [f"Show more {material} jewelry"]

            jewelry_type = _label_from_key("jewelry_type")
            if jewelry_type:
                return [f"Show more {jewelry_type} options"]

            design = _label_from_key("design")
            if design:
                return [f"Show more {design} designs"]

            category = _label_from_key("category")
            if category:
                return [f"Show more {category} items"]

            return ["Show more matching items"]

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
            debug_meta["clarify_questions"] = PipelinePresentationMixin._dedupe_follow_up_questions(list(questions or []), limit=2)
            debug_meta["clarify_suggestions"] = PipelinePresentationMixin._dedupe_follow_up_questions(list(suggestions or []), limit=3)

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
            product_result_count: int,
            product_display_count: int,
            product_has_more: bool,
        ) -> ChatResponseMeta:
            return ChatResponseMeta(
                query_summary=str(query_summary or ""),
                latency_ms=round(float(latency_ms), 2),
                source=source.value,
                llm_calls=int(llm_calls),
                embedding_calls=int(embedding_calls),
                product_result_count=int(product_result_count or 0),
                product_display_count=int(product_display_count or 0),
                product_has_more=bool(product_has_more),
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
    def _component_type_name(component: Any) -> str:
            raw_type = getattr(component, "type", "")
            return str(getattr(raw_type, "value", raw_type) or "").strip().lower()

    @staticmethod
    def _display_attribute_value(value: str) -> str:
            text = str(value or "").strip()
            if not text:
                return ""
            if text.islower():
                return " ".join([part.capitalize() for part in text.split(" ") if part])
            return text

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
                max_chars=int(getattr(settings, "CHAT_KNOWLEDGE_ANSWER_MAX_CHARS", 420)),
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
            normalized = normalize_user_text(question)
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
            looks_like_list = bool(
                re.search(r"(?:^|[\s;])\d+\.\s+", text)
                or re.search(r"(?:^|\s)[*-]\s+", text)
            )
            if looks_like_list:
                concise = text.strip()
            else:
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
                title = normalize_user_text(getattr(source, "title", ""))
                category = normalize_user_text(getattr(source, "category", ""))
                snippet = normalize_user_text(getattr(source, "content_snippet", ""))
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

    @classmethod
    def _build_component_contract(
            cls,
            *,
            context: ComponentContext,
            components,
            pick_text: Optional[Callable[[str, Sequence[str]], str]] = None,
        ) -> Dict[str, Any]:
            component_list: List[ChatComponent] = [item for item in list(components or []) if isinstance(item, ChatComponent)]
            mapped = cls._components_to_map(component_list)
            query_summary = str(mapped.get("query_summary", {}).get("text") or context.query_summary or "").strip()
            user_text = str(context.user_text or "").strip()
            choose = pick_text or (
                lambda key, variants: reply_tone.pick_variant(
                    user_text=user_text,
                    key=key,
                    variants=variants,
                )
            )
            assistant_text = ""
            carousel_msg = ""
            display_products: List[Any] = []
            follow_ups: List[str] = []
            has_knowledge_answer = "knowledge_answer" in mapped
            has_product_detail = "product_detail" in mapped
            has_product_cards = "product_cards" in mapped
            mixed_knowledge_answer = str(mapped.get("knowledge_answer", {}).get("answer") or "").strip()

            if "error" in mapped:
                assistant_text = str(mapped["error"].get("message") or "I could not process this request.")
            elif "clarify" in mapped:
                assistant_text = str(mapped["clarify"].get("message") or "Please share more details.")
                follow_ups.extend(list(context.debug.get("clarify_suggestions") or []))
            elif has_product_detail:
                detail_products = list(context.canonical_products or [])
                display_products = list(detail_products)
                assistant_text = str(context.debug.get("detail_reply_text") or "").strip() or query_summary
                carousel_msg = str(context.debug.get("detail_carousel_msg") or "").strip()
                follow_ups.extend(list(context.debug.get("detail_follow_ups") or []))
            elif has_product_cards:
                if bool(context.debug.get("detail_reply_text")):
                    display_products = list(context.canonical_products or [])
                else:
                    display_products, _total_unique_products = product_presentation.dedupe_products_by_master_code(
                        context.canonical_products,
                        limit=product_presentation.PRODUCT_DISPLAY_LIMIT,
                    )
                if bool(context.debug.get("store_overview_request")):
                    assistant_text = str(context.debug.get("store_overview_reply") or "").strip()
                    if not assistant_text:
                        assistant_text = cls._build_store_overview_reply(products=display_products)
                    follow_ups.extend(list(context.debug.get("store_overview_follow_ups") or []))
                elif bool(context.debug.get("detail_reply_text")):
                    assistant_text = str(context.debug.get("detail_reply_text") or "").strip()
                    carousel_msg = str(context.debug.get("detail_carousel_msg") or "").strip()
                    follow_ups.extend(list(context.debug.get("detail_follow_ups") or []))
                elif "recommendations" in mapped or bool(context.debug.get("recommendation_ranked_count")):
                    assistant_text = product_presentation.build_recommendation_match_reply(
                        attribute_filters=context.attribute_filters,
                        user_text=user_text,
                    )
                else:
                    assistant_text = product_presentation.build_product_match_reply(
                        attribute_filters=context.attribute_filters,
                        user_text=user_text,
                    )
                if not carousel_msg:
                    carousel_msg = choose(
                        f"{context.workflow}:carousel",
                        [
                            "Matching products are shown below.",
                            "These are the top matches for your request.",
                            "Here are the products that best fit your request.",
                        ],
                    )
                if bool(context.debug.get("catalog_pagination_requested")):
                    assistant_text = choose(
                        "catalog:pagination",
                        [
                            "Here are more matching products from your search.",
                            "I found more matching products from the same search.",
                            "Here are more options from your search.",
                        ],
                    )
                if not bool(context.debug.get("store_overview_request")):
                    follow_ups.extend(
                        cls._build_conversion_follow_ups(
                            products=display_products,
                            attribute_filters=context.attribute_filters,
                            user_text=user_text,
                            needs_knowledge=bool(context.debug.get("workflow_needs_knowledge", False)),
                            result_count=int(context.result_count or 0),
                            display_count=len(display_products or []),
                            display_offset=int(context.debug.get("catalog_pagination_offset", 0) or 0),
                            limit=5,
                            debug_meta=context.debug,
                        )
                    )
            elif has_knowledge_answer:
                assistant_text = mixed_knowledge_answer or query_summary

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

            if (has_product_detail or has_product_cards) and mixed_knowledge_answer:
                assistant_text = cls._combine_mixed_assistant_text(
                    product_text=assistant_text,
                    knowledge_text=mixed_knowledge_answer,
                )

            if not assistant_text:
                assistant_text = choose(
                    f"{context.workflow}:default_reply",
                    [
                        "I got it. Here's what I can do next.",
                        "Understood. Here's the best next step.",
                        "Thanks for the details. Here's what I found.",
                    ],
                )

            deduped_follow_ups = cls._dedupe_follow_up_questions(follow_ups, limit=5)
            rebuilt_components: List[ChatComponent] = []
            for component in component_list:
                kind = cls._component_type_name(component)
                if kind in {"assistant_message", "quick_replies"}:
                    continue
                if kind == "clarify":
                    clarify_data = dict(getattr(component, "data", {}) or {})
                    if deduped_follow_ups:
                        clarify_data["suggestions"] = list(deduped_follow_ups)
                    rebuilt_components.append(
                        ChatComponent(type=ChatComponentType.CLARIFY, data=clarify_data)
                    )
                    continue
                rebuilt_components.append(component)
            if assistant_text:
                rebuilt_components.insert(
                    0,
                    ChatComponent(
                        type=ChatComponentType.ASSISTANT_MESSAGE,
                        data={"text": str(assistant_text)},
                    ),
                )
            if deduped_follow_ups:
                rebuilt_components.append(
                    ChatComponent(
                        type=ChatComponentType.QUICK_REPLIES,
                        data={"items": list(deduped_follow_ups)},
                    )
                )

            product_carousel = component_contract.product_cards_from_components(rebuilt_components)
            if not product_carousel and list(display_products or []):
                product_carousel = [cls._to_product_card(item) for item in list(display_products or [])]

            return {
                "components": rebuilt_components,
                "assistant_text": str(assistant_text or ""),
                "carousel_msg": carousel_msg,
                "product_carousel": product_carousel,
                "follow_up_questions": list(deduped_follow_ups or []),
            }

    async def _finalize_pipeline_result(
            self,
            *,
            started: float,
            conversation_id: int,
            text: str,
            locale: str,
            workflow: str,
            route_decision: routing_policy.WorkflowDecision,
            routing_selection_source: str,
            detail: Any,
            sku_tokens: Sequence[str],
            query_summary: str,
            state: PipelineWorkflowState,
            debug_meta: Dict[str, Any],
            tone_pick: Callable[[str, Sequence[str]], str],
            tone_snapshot: Callable[[], Dict[str, Any]],
            llm_calls: int,
            embedding_calls: int,
            external_call_counts: Dict[str, int],
            spans: Dict[str, float],
            knowledge_workflow: bool,
            conversation_state_enabled: bool,
            state_working: Optional[Dict[str, Any]],
        ) -> ComponentPipelineResult:
            selected_components = state.selected_components
            canonical_products = state.canonical_products
            recommendations = state.recommendations
            knowledge_sources = state.knowledge_sources
            knowledge_answer = state.knowledge_answer
            result_count = state.result_count
            retrieval_source = state.retrieval_source
            ambiguity_reason = state.ambiguity_reason
            knowledge_error_message = state.knowledge_error_message

            if ComponentType.CLARIFY in selected_components:
                clarify_policy = self._build_clarify_policy(
                    reason=str(ambiguity_reason or "missing_details"),
                    user_text=text,
                    clarify_focus=str(getattr(detail, "clarify_focus", "") or ""),
                    tone_pick=tone_pick,
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

            contract = self._build_component_contract(
                context=context,
                components=components,
                pick_text=lambda key, variants: tone_pick(key, variants),
            )
            product_display_count = len(list(contract.get("product_carousel") or []))
            product_result_count = int(state.result_count or 0)
            product_has_more = bool(
                getattr(state, "pagination_has_more", False)
                or (product_result_count > product_display_count)
            )
            total_ms = (time.perf_counter() - started) * 1000.0
            meta = self._to_meta(
                query_summary=query_summary,
                source=retrieval_source,
                latency_ms=total_ms,
                llm_calls=llm_calls,
                embedding_calls=embedding_calls,
                product_result_count=product_result_count,
                product_display_count=product_display_count,
                product_has_more=product_has_more,
            )
            public_routing = route_decision.to_public_routing(
                execution_mode="component",
                selection_source=str(routing_selection_source or "component_pipeline"),
            )
            rebuilt_component_types = {
                self._component_type_name(component)
                for component in list(contract["components"] or [])
                if isinstance(component, ChatComponent)
            }
            public_routing.needs_clarification = "clarify" in rebuilt_component_types
            response = ChatResponse(
                conversation_id=conversation_id,
                reply_text=str(contract["assistant_text"]),
                carousel_msg=str(contract["carousel_msg"] or ""),
                product_carousel=list(contract["product_carousel"] or []),
                routing=public_routing,
                sources=knowledge_sources,
                debug={},
                components=list(contract["components"] or []),
                meta=meta,
            )

            tone_state = tone_snapshot()
            conversation_state_payload: Optional[Dict[str, Any]] = None
            if conversation_state_enabled and state_working is not None:
                response_cards = component_contract.product_cards_from_response(response)
                state_product_ids = conversation_state.product_ids_from_cards(response_cards)
                state_product_skus = conversation_state.product_skus_from_cards(response_cards)
                inventory_claim = {
                    "sku": str(debug_meta.get("inventory_verified_sku") or ""),
                    "stock_status": str(debug_meta.get("inventory_verified_status") or ""),
                    "last_stock_sync_at": str(debug_meta.get("inventory_last_stock_sync_at") or ""),
                }
                if not inventory_claim["sku"] and list(response_cards or []):
                    first_card = response_cards[0]
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
                        str(response_cards[0].currency or "")
                        if list(response_cards or [])
                        else ""
                    ),
                    route=workflow,
                    query_cache_key=str(state.query_cache_key or ""),
                    result_count=int(state.result_count or 0),
                    display_offset=int(debug_meta.get("catalog_pagination_offset") or 0),
                    display_limit=int(debug_meta.get("catalog_pagination_limit") or 0),
                    product_ids=state_product_ids,
                    product_skus=state_product_skus,
                    answer_source_ids=[str(source.source_id or "") for source in knowledge_sources if str(source.source_id or "").strip()],
                    inventory_claim=inventory_claim,
                    tone_recent=list(tone_state.get("recent") or []),
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
                    "tone_style": str(tone_state.get("style") or ""),
                    "tone_key": str(tone_state.get("key") or ""),
                    "tone_variant_id": tone_state.get("variant_id") if int(tone_state.get("variant_id", -1)) >= 0 else None,
                    "tone_anti_repeat_applied": bool(tone_state.get("anti_repeat_applied")),
                    "tone_repeat_hit": int(tone_state.get("repeat_hit", 0)),
                    "tone_filler_stripped": int(tone_state.get("filler_stripped", 0)),
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
