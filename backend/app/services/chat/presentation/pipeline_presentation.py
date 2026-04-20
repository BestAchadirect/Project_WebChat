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
from app.services.chat.presentation import (
    clarify_policy,
    component_contract_builder,
    component_contract,
    follow_up_builder,
    product_contract_builder,
    product_presentation,
)
from app.services.chat.components.builders.contextual_messages import generate_contextual_reply
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.pipeline_runtime.state import (
    ComponentPipelineResult,
    PipelineWorkflowState,
)
from app.services.chat.components.registry import ComponentRegistry
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.routing.contracts import WorkflowResult
from app.services.chat.text_normalization import normalize_user_text
from app.services.chat.retrieval.retrieval_outcome import build_retrieval_outcome



class PipelinePresentationMixin:
    @staticmethod
    def _top_source_relevance(sources: Sequence[KnowledgeSource]) -> float:
            return max((float(getattr(source, "relevance", 0.0) or 0.0) for source in list(sources or [])), default=0.0)

    @classmethod
    def _verify_workflow_result(
            cls,
            *,
            internal_workflow: str,
            state: PipelineWorkflowState,
            detail: Any,
        ) -> WorkflowResult:
            workflow = str(internal_workflow or "clarify").strip().lower()
            answerability = "none"
            verification_reason = "no_evidence"
            retrieval_confidence = 0.0
            evidence = {
                "product_count": int(len(list(state.presentation.canonical_products or []))),
                "knowledge_source_count": int(len(list(state.knowledge.sources or []))),
                "has_knowledge_answer": bool(str(state.knowledge.answer or "").strip()),
                "ambiguity_reason": str(state.decision.ambiguity_reason or ""),
            }
            if workflow in {"company_info", "policy_info"}:
                retrieval_confidence = cls._top_source_relevance(state.knowledge.sources)
                if str(state.decision.ambiguity_reason or "").strip():
                    answerability = "none"
                    verification_reason = str(state.decision.ambiguity_reason or "knowledge_needs_clarification")
                elif state.knowledge.sources and str(state.knowledge.answer or "").strip():
                    answerability = "full" if retrieval_confidence >= 0.6 else "partial"
                    verification_reason = "knowledge_sources_strong" if answerability == "full" else "knowledge_sources_weak"
                elif state.knowledge.sources:
                    answerability = "partial"
                    verification_reason = "knowledge_sources_without_answer"
            elif workflow == "mixed":
                product_ready = bool(list(state.presentation.canonical_products or []))
                knowledge_ready = bool(str(state.knowledge.answer or "").strip() or list(state.knowledge.sources or []))
                retrieval_confidence = max(
                    float(cls._top_source_relevance(state.knowledge.sources)),
                    1.0 if product_ready else 0.0,
                )
                if product_ready and knowledge_ready:
                    answerability = "full"
                    verification_reason = "mixed_full"
                elif product_ready or knowledge_ready:
                    answerability = "partial"
                    verification_reason = "mixed_partial"
            elif workflow in {"catalog_search", "product_detail"}:
                retrieval_confidence = 1.0 if list(state.presentation.canonical_products or []) else 0.0
                if str(state.decision.ambiguity_reason or "").strip():
                    answerability = "none"
                    verification_reason = str(state.decision.ambiguity_reason or "catalog_no_results")
                elif list(state.presentation.canonical_products or []):
                    answerability = "full"
                    verification_reason = "catalog_results_available" if workflow == "catalog_search" else "detail_result_available"
                elif bool(getattr(detail, "is_detail_request", False)):
                    verification_reason = "detail_request_needs_specific_product"
            elif workflow in {"smalltalk", "off_topic"}:
                answerability = "full"
                retrieval_confidence = 1.0
                verification_reason = "terminal_response"
            elif workflow == "clarify":
                answerability = "none"
                verification_reason = str(state.decision.ambiguity_reason or "clarify_requested")

            return WorkflowResult(
                internal_workflow=workflow,
                retrieval_source=str(getattr(state.retrieval.source, "value", state.retrieval.source) or "error"),
                answerability=answerability,
                retrieval_confidence=retrieval_confidence,
                verification_reason=verification_reason,
                evidence=evidence,
                render_inputs={
                    "selected_components": [component.value for component in list(state.presentation.selected_components or [])],
                    "requested_fields": list(getattr(detail, "requested_fields", []) or []),
                },
            )

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
            return clarify_policy.dedupe_follow_up_questions(items, limit=limit)

    @staticmethod
    def _product_sku(product: Any) -> str:
            return clarify_policy.product_sku(product)

    @classmethod
    def _build_product_clarify_follow_ups(
            cls,
            *,
            products: Sequence[Any],
            attribute_filters: Dict[str, str],
            needs_knowledge: bool,
            limit: int = 3,
        ) -> List[str]:
            return clarify_policy.build_product_clarify_follow_ups(
                products=products,
                attribute_filters=attribute_filters,
                needs_knowledge=needs_knowledge,
                limit=limit,
            )

    @classmethod
    def _build_knowledge_clarify_follow_ups(
            cls,
            *,
            user_text: str,
            limit: int = 3,
        ) -> List[str]:
            return clarify_policy.build_knowledge_clarify_follow_ups(
                user_text=user_text,
                location_terms=cls._LOCATION_KNOWLEDGE_TERMS,
                contact_terms=cls._CONTACT_KNOWLEDGE_TERMS,
                shipping_terms=cls._SHIPPING_KNOWLEDGE_TERMS,
                refund_terms=cls._REFUND_KNOWLEDGE_TERMS,
                payment_terms=cls._PAYMENT_KNOWLEDGE_TERMS,
                warranty_terms=cls._WARRANTY_KNOWLEDGE_TERMS,
                limit=limit,
            )

    @classmethod
    def _knowledge_clarify_focus(cls, *, user_text: str) -> str:
            return clarify_policy.knowledge_clarify_focus(
                user_text=user_text,
                location_terms=cls._LOCATION_KNOWLEDGE_TERMS,
                contact_terms=cls._CONTACT_KNOWLEDGE_TERMS,
                shipping_terms=cls._SHIPPING_KNOWLEDGE_TERMS,
                refund_terms=cls._REFUND_KNOWLEDGE_TERMS,
                payment_terms=cls._PAYMENT_KNOWLEDGE_TERMS,
                warranty_terms=cls._WARRANTY_KNOWLEDGE_TERMS,
            )

    @classmethod
    def _knowledge_clarify_question(cls, *, user_text: str) -> str:
            return clarify_policy.knowledge_clarify_question(
                user_text=user_text,
                location_terms=cls._LOCATION_KNOWLEDGE_TERMS,
                contact_terms=cls._CONTACT_KNOWLEDGE_TERMS,
                shipping_terms=cls._SHIPPING_KNOWLEDGE_TERMS,
                refund_terms=cls._REFUND_KNOWLEDGE_TERMS,
                payment_terms=cls._PAYMENT_KNOWLEDGE_TERMS,
                warranty_terms=cls._WARRANTY_KNOWLEDGE_TERMS,
            )

    @classmethod
    async def _build_clarify_policy(
            cls,
            *,
            reason: str,
            user_text: str,
            reply_language: str,
            products: Sequence[Any],
            attribute_filters: Dict[str, str],
            needs_knowledge: bool,
            requested_fields: Sequence[str],
            clarify_focus: str = "",
        ) -> Dict[str, Any]:
            return await clarify_policy.build_clarify_policy(
                reason=reason,
                user_text=user_text,
                reply_language=reply_language,
                products=products,
                attribute_filters=attribute_filters,
                needs_knowledge=needs_knowledge,
                requested_fields=requested_fields,
                clarify_focus=clarify_focus,
                display_attribute_value=cls._display_attribute_value,
                build_pagination_exhausted_follow_ups=cls._build_pagination_exhausted_follow_ups,
                location_terms=cls._LOCATION_KNOWLEDGE_TERMS,
                contact_terms=cls._CONTACT_KNOWLEDGE_TERMS,
                shipping_terms=cls._SHIPPING_KNOWLEDGE_TERMS,
                refund_terms=cls._REFUND_KNOWLEDGE_TERMS,
                payment_terms=cls._PAYMENT_KNOWLEDGE_TERMS,
                warranty_terms=cls._WARRANTY_KNOWLEDGE_TERMS,
            )

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
            def _show_more_follow_up_adapter(
                    *,
                    products: Sequence[Any],
                    attribute_filters: Dict[str, str],
                    result_count: int,
                    display_count: int,
                    display_offset: int = 0,
                    pagination_has_more: Optional[bool] = None,
                ) -> List[str]:
                try:
                    return cls._build_show_more_follow_up(
                        products=products,
                        attribute_filters=attribute_filters,
                        result_count=result_count,
                        display_count=display_count,
                        display_offset=display_offset,
                        pagination_has_more=pagination_has_more,
                    )
                except TypeError:
                    return cls._build_show_more_follow_up(
                        products=products,
                        attribute_filters=attribute_filters,
                        result_count=result_count,
                        display_count=display_count,
                        display_offset=display_offset,
                    )

            return follow_up_builder.build_conversion_follow_ups(
                products=products,
                attribute_filters=attribute_filters,
                user_text=user_text,
                needs_knowledge=needs_knowledge,
                result_count=result_count,
                display_count=display_count,
                display_offset=display_offset,
                limit=limit,
                debug_meta=debug_meta,
                top_product_attributes=cls._top_product_attributes,
                build_show_more_follow_up=_show_more_follow_up_adapter,
                dedupe_follow_up_questions=cls._dedupe_follow_up_questions,
            )

    @classmethod
    def _build_show_more_follow_up(
            cls,
            *,
            products: Sequence[Any],
            attribute_filters: Dict[str, str],
            result_count: int,
            display_count: int,
            display_offset: int = 0,
            pagination_has_more: Optional[bool] = None,
        ) -> List[str]:
            return follow_up_builder.build_show_more_follow_up(
                products=products,
                attribute_filters=attribute_filters,
                result_count=result_count,
                display_count=display_count,
                display_offset=display_offset,
                pagination_has_more=pagination_has_more,
                display_attribute_value=cls._display_attribute_value,
                top_product_attributes=cls._top_product_attributes,
            )

    @classmethod
    def _build_pagination_exhausted_follow_ups(
            cls,
            *,
            attribute_filters: Dict[str, str],
            limit: int = 3,
        ) -> List[str]:
            return follow_up_builder.build_pagination_exhausted_follow_ups(
                attribute_filters=attribute_filters,
                limit=limit,
                display_attribute_value=cls._display_attribute_value,
                dedupe_follow_up_questions=cls._dedupe_follow_up_questions,
            )

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
            snippet = str(getattr(top[0], "content_snippet", "") or "").strip()
            if not snippet:
                return "I couldn't find enough details yet. Could you clarify what you need?"
            return cls._polish_grounded_knowledge_answer(
                answer=snippet,
                question=question,
                max_sentences=2,
                max_chars=int(getattr(settings, "CHAT_KNOWLEDGE_ANSWER_MAX_CHARS", 420)),
            )

    @classmethod
    def _polish_grounded_knowledge_answer(
            cls,
            *,
            answer: str,
            question: str,
            max_sentences: int = 2,
            max_chars: int = 240,
        ) -> str:
            text = str(answer or "")
            text = re.sub(r"^\s*here is what i found:\s*", "", text, flags=re.IGNORECASE)

            list_items: List[str] = []
            trailing_sentences: List[str] = []
            for raw_line in text.splitlines():
                line = cls._clean_knowledge_snippet_text(raw_line)
                if not line:
                    continue
                is_bullet = bool(re.match(r"^(?:[•●\-\*]|\d+\.)\s+", line))
                cleaned_line = re.sub(r"^(?:[•●\-\*]|\d+\.)\s*", "", line).strip(" .;:")
                if not cleaned_line:
                    continue
                if is_bullet:
                    list_items.append(cleaned_line)
                else:
                    trailing_sentences.append(cleaned_line)

            if len(list_items) >= 2:
                concise = "; ".join(list_items[:3])
                if len(list_items) > 3:
                    concise = f"{concise}; and {list_items[3]}"
                if trailing_sentences:
                    concise = f"{concise}. {' '.join(trailing_sentences)}"
            else:
                concise = cls._clean_knowledge_snippet_text(text)
                heading_match = re.match(r"^\s*([A-Za-z][A-Za-z\s/&-]{1,32}):\s*(.+)$", concise)
                if heading_match:
                    heading = str(heading_match.group(1) or "").strip()
                    body = str(heading_match.group(2) or "").strip()
                    if 1 <= len(heading.split()) <= 3 and len(body.split()) >= 4:
                        concise = body
                sentences = cls._extract_sentences(concise, limit=max_sentences)
                concise = " ".join(sentences).strip() if sentences else concise.strip()

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
            heading_match = re.match(r"^\s*([A-Za-z][A-Za-z\s/&-]{1,32}):\s*(.+)$", text)
            heading_stripped = False
            if heading_match:
                heading = str(heading_match.group(1) or "").strip()
                body = str(heading_match.group(2) or "").strip()
                if 1 <= len(heading.split()) <= 3 and len(body.split()) >= 4:
                    text = body
                    heading_stripped = True
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
    async def _build_component_contract(
            cls,
            *,
            context: ComponentContext,
            components,
        ) -> Dict[str, Any]:
            component_list: List[ChatComponent] = [item for item in list(components or []) if isinstance(item, ChatComponent)]
            mapped = cls._components_to_map(component_list)
            query_summary = str(mapped.get("query_summary", {}).get("text") or context.query_summary or "").strip()
            user_text = str(context.user_text or "").strip()
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
                product_contract = await product_contract_builder.build_product_cards_contract(
                    context=context,
                    mapped=mapped,
                    build_store_overview_reply=cls._build_store_overview_reply,
                    build_show_more_follow_up=cls._build_show_more_follow_up,
                    build_conversion_follow_ups=cls._build_conversion_follow_ups,
                )
                assistant_text = str(product_contract.get("assistant_text") or "")
                carousel_msg = str(product_contract.get("carousel_msg") or "")
                display_products = list(product_contract.get("display_products") or [])
                follow_ups.extend(list(product_contract.get("follow_ups") or []))
            elif has_knowledge_answer:
                assistant_text = mixed_knowledge_answer or query_summary

            if (has_product_detail or has_product_cards) and mixed_knowledge_answer:
                assistant_text = cls._combine_mixed_assistant_text(
                    product_text=assistant_text,
                    knowledge_text=mixed_knowledge_answer,
                )

            if not assistant_text:
                assistant_text = await generate_contextual_reply(
                    kind="default",
                    reply_language=str(getattr(context, "locale", "") or "en-US"),
                    payload={
                        "user_text": user_text,
                        "query_summary": query_summary,
                        "workflow": str(context.workflow or ""),
                        "source": str(getattr(context.source, "value", context.source) or ""),
                        "result_count": int(getattr(context, "result_count", 0) or 0),
                        "has_products": bool(list(getattr(context, "canonical_products", []) or [])),
                        "has_knowledge": bool(list(getattr(context, "knowledge_sources", []) or [])),
                        "attribute_filters": dict(getattr(context, "attribute_filters", {}) or {}),
                        "sku_tokens": list(getattr(context, "sku_tokens", []) or []),
                    },
                )
                if not assistant_text:
                    assistant_text = "I got it. Here's what I can do next."

            finalized_contract = component_contract_builder.finalize_contract_components(
                component_list=component_list,
                assistant_text=assistant_text,
                follow_ups=follow_ups,
                display_products=display_products,
                dedupe_follow_up_questions=cls._dedupe_follow_up_questions,
                component_type_name=cls._component_type_name,
                to_product_card=cls._to_product_card,
            )

            return {
                "components": list(finalized_contract["components"] or []),
                "assistant_text": str(assistant_text or ""),
                "carousel_msg": carousel_msg,
                "product_carousel": list(finalized_contract["product_carousel"] or []),
                "follow_up_questions": list(finalized_contract["follow_up_questions"] or []),
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
            internal_workflow: str,
            detail: Any,
            sku_tokens: Sequence[str],
            query_summary: str,
            state: PipelineWorkflowState,
            debug_meta: Dict[str, Any],
            tone_snapshot: Callable[[], Dict[str, Any]],
            llm_calls: int,
            embedding_calls: int,
            external_call_counts: Dict[str, int],
            spans: Dict[str, float],
            knowledge_workflow: bool,
            conversation_state_enabled: bool,
            state_working: Optional[Dict[str, Any]],
        ) -> ComponentPipelineResult:
            selected_components = state.presentation.selected_components
            canonical_products = state.presentation.canonical_products
            knowledge_sources = state.knowledge.sources
            knowledge_answer = state.knowledge.answer
            result_count = state.retrieval.result_count
            retrieval_source = state.retrieval.source
            ambiguity_reason = state.decision.ambiguity_reason
            knowledge_error_message = state.knowledge.error_message
            retrieval_outcome = build_retrieval_outcome(
                retrieval_source=retrieval_source,
                product_ids=list(state.catalog.product_ids or []),
                ambiguity_reason=str(ambiguity_reason or ""),
            )
            state.retrieval.outcome = retrieval_outcome
            debug_meta["retrieval_outcome"] = retrieval_outcome.to_debug_dict()
            debug_meta["match_tier"] = retrieval_outcome.match_tier

            if ComponentType.CLARIFY in selected_components:
                clarify_policy = await self._build_clarify_policy(
                    reason=str(ambiguity_reason or "missing_details"),
                    user_text=text,
                    reply_language=locale,
                    clarify_focus=str(getattr(detail, "clarify_focus", "") or ""),
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

            workflow_result = self._verify_workflow_result(
                internal_workflow=internal_workflow,
                state=state,
                detail=detail,
            )
            state.decision.workflow_result = workflow_result
            state.decision.retrieval_confidence = float(workflow_result.retrieval_confidence or 0.0)
            state.decision.answerability = str(workflow_result.answerability or "none")
            state.decision.verification_reason = str(workflow_result.verification_reason or "")
            debug_meta["internal_workflow"] = workflow_result.internal_workflow
            debug_meta["retrieval_confidence"] = workflow_result.retrieval_confidence
            debug_meta["answerability"] = workflow_result.answerability
            debug_meta["verification_reason"] = workflow_result.verification_reason
            debug_meta["workflow_evidence"] = dict(workflow_result.evidence or {})

            context = ComponentContext(
                user_text=text,
                locale=locale,
                workflow=workflow,
                query_summary=query_summary,
                source=retrieval_source,
                selected_components=selected_components,
                canonical_products=canonical_products,
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

            contract = await self._build_component_contract(
                context=context,
                components=components,
            )
            product_display_count = len(list(contract.get("product_carousel") or []))
            product_result_count = int(state.retrieval.result_count or 0)
            product_has_more = bool(
                state.catalog.pagination_has_more
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
                    query_cache_key=str(state.catalog.query_cache_key or ""),
                    query_product_ids=list(state.catalog.query_product_ids or state.catalog.product_ids or []),
                    result_count=int(state.retrieval.result_count or 0),
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
