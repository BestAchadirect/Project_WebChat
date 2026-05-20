from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any, Sequence
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse, ProductCard
from app.services.ai.llm_service import llm_service
from app.services.catalog.product_search import ProductSearchResult
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.parsing.detail_query_parser import DetailQuery
from app.services.chat.parsing.llm_attribute_extractor import DetailQueryInferenceResult
from app.services.chat.routing.contracts import UnderstandingResult
from app.services.chat.runtime import conversation_state
from app.services.chat.service import ChatService
from app.services.chat.text_normalization import normalize_user_text
from tests.fixtures.chat import DummyConversation, RedisStub


def _stable_uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"project-webchat-eval:{value}")


def _product(
    *,
    key: str,
    sku: str,
    title: str,
    material: str,
    jewelry_type: str,
    stock_status: str = "in_stock",
    color: str = "",
    opal_color: str = "",
    description: str = "",
    master_code: str = "",
) -> CanonicalProduct:
    normalized_master_code = master_code or sku
    return CanonicalProduct(
        product_id=_stable_uuid(key),
        sku=sku,
        title=title,
        price=Decimal("12.50"),
        currency="USD",
        in_stock=stock_status == "in_stock",
        stock_qty=5 if stock_status == "in_stock" else 0,
        material=material,
        gauge="14g",
        image_url=None,
        description=description or title,
        attributes={
            "master_code": normalized_master_code,
            "material": material,
            "jewelry_type": jewelry_type,
            **({"color": color} if color else {}),
            **({"opal_color": opal_color} if opal_color else {}),
        },
        product_url=f"https://example.com/{sku.lower()}",
    )


PRODUCT_FIXTURES = [
    _product(
        key="lab-ti-1",
        sku="LAB-TI-1",
        title="Titanium Labret",
        material="titanium",
        jewelry_type="labret",
        color="silver",
    ),
    _product(
        key="lab-gold-1",
        sku="LAB-GOLD-1",
        title="Gold Labret",
        material="gold",
        jewelry_type="labret",
        stock_status="out_of_stock",
        color="gold",
    ),
    _product(
        key="dmbj38",
        sku="DMBJ38",
        title="DMBJ38 Labret",
        material="titanium g23",
        jewelry_type="labret",
        description="Threadless implant-grade titanium labret.",
        master_code="DMBJ38",
    ),
    _product(
        key="nr-black-ti-1",
        sku="NR-BLACK-TI-1",
        title="Black Titanium Nose Ring",
        material="titanium",
        jewelry_type="nose ring",
        color="black",
    ),
    _product(
        key="opal-lab-1",
        sku="OPAL-LAB-1",
        title="Opal Labret",
        material="titanium",
        jewelry_type="labret",
        color="opal",
        opal_color="opal",
    ),
]


def _card_from_product(product: CanonicalProduct) -> ProductCard:
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
        attributes=dict(product.attributes or {}),
    )


class _ConversationStateQueryResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def first(self) -> tuple[dict[str, Any]]:
        return (self._payload,)


class MutableConversationStateDB:
    def __init__(self) -> None:
        self.payload = conversation_state.load_state(None)

    async def execute(self, *args: Any, **kwargs: Any) -> _ConversationStateQueryResult:
        del args, kwargs
        return _ConversationStateQueryResult(self.payload)


class DeterministicKnowledgeStub:
    async def search(self, *args: Any, **kwargs: Any) -> list[Any]:
        del args, kwargs
        return []


class DeterministicCatalogStub:
    def __init__(self, products: Sequence[CanonicalProduct]) -> None:
        self.products = list(products)
        self.by_id = {str(product.product_id): product for product in self.products}
        self.by_sku = {product.sku.lower(): product for product in self.products}
        self.last_metrics: dict[str, float] = {"vector_search_ms": 0.0, "db_product_lookup_ms": 0.0}
        self.last_meta: dict[str, Any] = {}

    def structured_cache_stats(self) -> dict[str, Any]:
        return {"size": 0, "hits": 0, "misses": 0, "hit_rate": 0.0}

    @staticmethod
    def _normalize_value(value: Any) -> str:
        return normalize_user_text(str(value or ""))

    def _normalize_filters(self, filters: dict[str, str] | None) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_value in dict(filters or {}).items():
            key = str(raw_key or "").strip().lower()
            if key == "product_type":
                key = "jewelry_type"
            value = self._normalize_value(raw_value)
            if key and value:
                normalized[key] = value
        return normalized

    def _matches_filters(self, product: CanonicalProduct, filters: dict[str, str]) -> bool:
        attrs = {
            str(key).lower(): self._normalize_value(value)
            for key, value in dict(product.attributes or {}).items()
        }
        for key, expected in filters.items():
            actual = attrs.get(key, "")
            if not actual:
                return False
            if key == "material":
                if expected not in actual and actual not in expected:
                    return False
                continue
            if actual != expected:
                return False
        return True

    def _matches_query(self, product: CanonicalProduct, query_text: str) -> bool:
        text = self._normalize_value(query_text)
        if not text:
            return False
        attrs = dict(product.attributes or {})
        haystack = " ".join(
            [
                product.sku,
                str(attrs.get("master_code") or ""),
                product.title,
                product.description or "",
                str(attrs.get("material") or ""),
                str(attrs.get("jewelry_type") or ""),
                str(attrs.get("color") or ""),
                str(attrs.get("opal_color") or ""),
            ]
        )
        haystack_norm = self._normalize_value(haystack)
        tokens = [token for token in text.split() if token]
        return bool(tokens) and all(token in haystack_norm for token in tokens)

    def _search(
        self,
        *,
        sku_token: str = "",
        attribute_filters: dict[str, str] | None = None,
        query_text: str = "",
    ) -> list[CanonicalProduct]:
        if sku_token:
            normalized = self._normalize_value(sku_token)
            matches = [
                product
                for product in self.products
                if normalized in {
                    self._normalize_value(product.sku),
                    self._normalize_value((product.attributes or {}).get("master_code")),
                }
            ]
            if matches:
                return matches

        filters = self._normalize_filters(attribute_filters)
        matches = [
            product
            for product in self.products
            if (not filters or self._matches_filters(product, filters))
            and (not query_text or self._matches_query(product, query_text))
        ]
        if matches:
            return matches

        if query_text:
            return [product for product in self.products if self._matches_query(product, query_text)]
        return []

    def _build_result(
        self,
        matches: Sequence[CanonicalProduct],
        *,
        limit: int,
        return_ids_only: bool = False,
    ) -> ProductSearchResult:
        limited = list(matches[: max(1, int(limit))])
        product_ids = [str(product.product_id) for product in limited]
        cards = [] if return_ids_only else [_card_from_product(product) for product in limited]
        return ProductSearchResult(
            cards=cards,
            distances=[0.0 for _ in cards],
            best_distance=0.0 if limited else None,
            distance_by_id={str(product.product_id): 0.0 for product in limited},
            product_ids=product_ids,
        )

    async def structured_search(
        self,
        *,
        sku_token: str | None = None,
        attribute_filters: dict[str, str] | None = None,
        limit: int = 10,
        return_ids_only: bool = False,
        **kwargs: Any,
    ) -> tuple[ProductSearchResult, dict[str, Any]]:
        del kwargs
        matches = self._search(sku_token=str(sku_token or ""), attribute_filters=attribute_filters)
        return self._build_result(matches, limit=limit, return_ids_only=return_ids_only), {}

    async def smart_search(
        self,
        *,
        query_text: str = "",
        attribute_filters: dict[str, str] | None = None,
        limit: int = 10,
        **kwargs: Any,
    ) -> ProductSearchResult:
        del kwargs
        matches = self._search(query_text=query_text, attribute_filters=attribute_filters)
        return self._build_result(matches, limit=limit)

    async def vector_search(self, *args: Any, **kwargs: Any) -> ProductSearchResult:
        del args
        matches = self._search(
            query_text=str(kwargs.get("query_text") or kwargs.get("query") or ""),
            attribute_filters=kwargs.get("attribute_filters") or kwargs.get("filters") or kwargs.get("hard_filters"),
            sku_token=str(kwargs.get("sku_token") or ""),
        )
        return self._build_result(matches, limit=int(kwargs.get("limit") or 10))

    async def lexical_search(self, *args: Any, **kwargs: Any) -> ProductSearchResult:
        return await self.vector_search(*args, **kwargs)

    async def structured_count(
        self,
        *,
        sku_token: str | None = None,
        attribute_filters: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> int:
        del kwargs
        matches = self._search(sku_token=str(sku_token or ""), attribute_filters=attribute_filters)
        return len(matches)

    async def get_product_by_sku(self, sku: str) -> ProductCard | None:
        product = self.by_sku.get(str(sku or "").strip().lower())
        return _card_from_product(product) if product is not None else None

    async def resolve_product_reference(self, reference: str, *, max_candidates: int = 5) -> dict[str, Any]:
        normalized = self._normalize_value(reference)
        matches = [
            product
            for product in self.products
            if normalized in {
                self._normalize_value(product.sku),
                self._normalize_value((product.attributes or {}).get("master_code")),
            }
        ]
        if len(matches) == 1:
            return {
                "status": "resolved",
                "reference": reference,
                "matched_by": "direct_reference",
                "product": _card_from_product(matches[0]),
            }
        if len(matches) > 1:
            return {
                "status": "ambiguous",
                "reference": reference,
                "matched_by": "direct_reference",
                "candidates": [_card_from_product(product) for product in matches[:max_candidates]],
            }
        return {"status": "not_found", "reference": reference, "matched_by": ""}

    async def get_inventory_snapshot(self, sku: str) -> dict[str, Any]:
        product = self.by_sku.get(str(sku or "").strip().lower())
        if product is None:
            return {"found": False, "sku": sku, "source": "db"}
        return {
            "found": True,
            "sku": product.sku,
            "stock_status": "in_stock" if product.in_stock else "out_of_stock",
            "last_stock_sync_at": None,
            "source": "db",
        }


def _extract_product_code(text: str) -> str:
    match = re.search(r"\b(?=[A-Z0-9-]*\d)([A-Z]{2,}[A-Z0-9-]{2,})\b", str(text or ""), flags=re.IGNORECASE)
    return str(match.group(1) if match else "").upper()


def _understanding(
    *,
    normalized_text: str,
    workflow_hypothesis: str,
    intent_confidence: float = 0.9,
    reason: str,
    needs_products: bool = False,
    needs_knowledge: bool = False,
    intent: str = "clarify",
    subintent: str = "",
    response_policy: str = "ask_clarifying_question",
    clarify_question: str = "",
    pending_task_type: str = "",
    missing_slot: str = "",
    product_query: str = "",
) -> UnderstandingResult:
    return UnderstandingResult(
        normalized_text=normalized_text,
        locale="en-US",
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis=workflow_hypothesis,
        intent_confidence=intent_confidence,
        reason=reason,
        needs_products=needs_products,
        needs_knowledge=needs_knowledge,
        intent=intent,
        subintent=subintent,
        product_query=product_query,
        response_policy=response_policy,
        clarify_question=clarify_question,
        pending_task_type=pending_task_type,
        missing_slot=missing_slot,
        debug={"understanding_source": "evaluation_fixture"},
    )


@dataclass(frozen=True)
class ChatEvalResult:
    answer_text: str
    internal_workflow: str | None
    public_workflow: str | None
    filters: dict[str, str]
    should_clarify: bool
    pending_task_type: str | None
    missing_slot: str | None
    product_anchor: str | None
    conversation_state: dict[str, Any]
    raw_debug: dict[str, Any]


@dataclass(frozen=True)
class ChatEvalTurn:
    user_message: str
    response: ChatResponse
    result: ChatEvalResult


class ChatEvalHarness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.user_id = "eval-user"
        self.conversation_id = 901
        self.current_state = conversation_state.load_state(None)
        self.state_db = MutableConversationStateDB()
        self.catalog = DeterministicCatalogStub(PRODUCT_FIXTURES)
        self.knowledge = DeterministicKnowledgeStub()
        self.last_component_result: Any = None
        self.turns: list[ChatEvalTurn] = []
        self._patch_environment()

    def _patch_environment(self) -> None:
        async def fake_get_or_create_user(
            self_service: ChatService,
            user_id: str,
            name: str | None = None,
            email: str | None = None,
        ) -> Any:
            del self_service
            return SimpleNamespace(id=user_id, customer_name=name, email=email)

        async def fake_get_or_create_conversation(
            self_service: ChatService,
            user: Any,
            conversation_id: int | None,
        ) -> DummyConversation:
            del self_service, user, conversation_id
            return DummyConversation(conversation_id=self.conversation_id)

        async def fake_finalize_response(
            self_service: ChatService,
            *,
            response: ChatResponse,
            **kwargs: Any,
        ) -> ChatResponse:
            del self_service, kwargs
            return response

        async def fake_get_conversation_state(
            self_service: ChatService,
            conversation_id: int,
        ) -> dict[str, Any]:
            del self_service, conversation_id
            return conversation_state.load_state(self.current_state)

        async def fake_understanding(**kwargs: Any) -> UnderstandingResult:
            return self._build_understanding(kwargs.get("user_text", ""))

        async def fake_infer_detail_query(**kwargs: Any) -> DetailQueryInferenceResult:
            return self._build_detail_inference(kwargs.get("user_text", ""), kwargs.get("existing_filters"))

        async def fake_generate_embedding(text: str) -> list[float]:
            del text
            return [0.1, 0.2, 0.3]

        async def fake_get_alias_map(db: Any) -> dict[str, dict[str, str]]:
            del db
            return {}

        async def fake_get_parser_rules(db: Any) -> Any:
            del db
            from app.services.chat.parsing import parser_rule_cache

            return parser_rule_cache.get_cached_parser_rules()

        async def fake_get_searchable_attribute_metadata(db: Any) -> list[dict[str, Any]]:
            del db
            return []

        async def wrapped_component_pipeline(
            service: ChatService,
            *,
            request: ChatRequest,
            conversation_id: int,
            run_id: str,
            **kwargs: Any,
        ) -> Any:
            del service
            self.state_db.payload = conversation_state.load_state(self.current_state)
            pipeline = ComponentPipeline(
                db=self.state_db,
                catalog_search=self.catalog,
                knowledge_retrieval=self.knowledge,
                redis_cache=RedisStub(),
            )

            async def fake_resolve(
                *,
                product_ids: Sequence[str],
                component_types: Sequence[Any],
                component_cache: Any | None = None,
                redis_cache: Any | None = None,
            ) -> tuple[list[CanonicalProduct], dict[str, Any]]:
                del component_types, component_cache, redis_cache
                resolved = [
                    self.catalog.by_id[str(product_id)]
                    for product_id in list(product_ids or [])
                    if str(product_id) in self.catalog.by_id
                ]
                return resolved, {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

            pipeline._field_resolver.resolve = fake_resolve  # type: ignore[method-assign]
            result = await pipeline.run(
                request=request,
                conversation_id=conversation_id,
                run_id=run_id,
                **kwargs,
            )
            self.last_component_result = result
            if result.conversation_state is not None:
                self.current_state = conversation_state.load_state(result.conversation_state)
                self.state_db.payload = dict(self.current_state)
            return result

        self.monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False)
        self.monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
        self.monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
        self.monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
        self.monkeypatch.setattr(settings, "CHAT_FIELD_AWARE_DETAIL_ENABLED", False)
        self.monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True)
        self.monkeypatch.setattr(settings, "CHAT_QUERY_UNDERSTANDING_V2_ENABLED", False)
        self.monkeypatch.setattr(settings, "CHAT_TONE_HUMANIZER_ENABLED", False)
        self.monkeypatch.setattr(llm_service, "begin_token_tracking", lambda: None)
        self.monkeypatch.setattr(llm_service, "consume_token_usage", lambda: {})
        self.monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
        self.monkeypatch.setattr(ChatService, "get_or_create_user", fake_get_or_create_user)
        self.monkeypatch.setattr(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
        self.monkeypatch.setattr(ChatService, "_finalize_response", fake_finalize_response)
        self.monkeypatch.setattr(ChatService, "get_conversation_state", fake_get_conversation_state)
        self.monkeypatch.setattr(ChatService, "_run_component_pipeline", wrapped_component_pipeline)
        self.monkeypatch.setattr("app.services.chat.harness.dependencies.build_understanding_result", fake_understanding)
        self.monkeypatch.setattr("app.services.chat.harness.dependencies.infer_detail_query", fake_infer_detail_query)
        self.monkeypatch.setattr(
            "app.services.chat.components.pipeline_runtime.setup.alias_cache.get_alias_map",
            fake_get_alias_map,
        )
        self.monkeypatch.setattr(
            "app.services.chat.components.pipeline_runtime.setup.parser_rule_cache.get_parser_rules",
            fake_get_parser_rules,
        )
        self.monkeypatch.setattr(
            "app.services.chat.components.pipeline_runtime.setup.eav_service.get_searchable_attribute_metadata",
            fake_get_searchable_attribute_metadata,
        )

    def _has_catalog_context(self) -> bool:
        state = conversation_state.load_state(self.current_state)
        return bool(dict(state.get("last_attribute_filters") or {}))

    def _build_understanding(self, user_text: str) -> UnderstandingResult:
        normalized = normalize_user_text(user_text)
        code = _extract_product_code(user_text)
        has_context = self._has_catalog_context()

        if normalized in {"where is it made", "where is it made?"}:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="clarify",
                reason="missing_product_anchor",
                intent="clarify",
                subintent="origin_question",
                response_policy="ask_clarifying_question",
                clarify_question="Which product are you asking about?",
                pending_task_type="product_origin_question",
                missing_slot="product_anchor",
            )

        if normalized in {"tell me material", "show me product info", "product info"}:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="clarify",
                reason="missing_product_anchor",
                intent="clarify",
                subintent="product_information",
                response_policy="ask_clarifying_question",
                clarify_question="Which product are you asking about?",
                pending_task_type="product_details_question",
                missing_slot="product_anchor",
            )

        if normalized in {"what about that one", "what about that one?", "what about it", "what about it?"}:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="clarify",
                reason="context_missing_anchor",
                intent="clarify",
                response_policy="ask_clarifying_question",
                clarify_question="Could you clarify which product you mean?",
            )

        if normalized == "gold one" and not has_context:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="clarify",
                reason="context_missing_anchor",
                intent="clarify",
                response_policy="ask_clarifying_question",
                clarify_question="Could you clarify which product you mean?",
            )

        if "sterilization with opal" in normalized:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="policy_info",
                reason="ambiguous_policy_or_product_request",
                needs_knowledge=True,
                intent="knowledge_policy",
                response_policy="answer_from_retrieved_data",
            )

        if "unicorn coating" in normalized:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="clarify",
                reason="unsupported_attribute",
                intent="clarify",
                response_policy="ask_clarifying_question",
                clarify_question="Could you clarify which supported attribute matters most?",
            )

        if code:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="product_detail",
                reason="explicit_product_code",
                needs_products=True,
                intent="product_information",
                subintent="product_detail",
                response_policy="answer_from_retrieved_data",
                product_query=code,
            )

        if "show me gold labret" in normalized:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="catalog_search",
                reason="catalog_browse",
                needs_products=True,
                intent="product_information",
                subintent="product_search",
                response_policy="answer_from_retrieved_data",
            )

        if "show me labret" in normalized or normalized == "show me labret":
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="catalog_search",
                reason="catalog_browse",
                needs_products=True,
                intent="product_information",
                subintent="product_search",
                response_policy="answer_from_retrieved_data",
            )

        if "what about gold" in normalized or normalized == "gold one":
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="catalog_search",
                reason="catalog_refinement",
                needs_products=True,
                intent="product_information",
                subintent="product_search",
                response_policy="answer_from_retrieved_data",
            )

        if "show me gld labrt" in normalized:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="catalog_search",
                reason="catalog_browse",
                needs_products=True,
                intent="product_information",
                subintent="product_search",
                response_policy="answer_from_retrieved_data",
            )

        if "opal gold" in normalized:
            return _understanding(
                normalized_text=normalized,
                workflow_hypothesis="catalog_search",
                reason="ambiguous_material_or_color",
                needs_products=True,
                intent="product_information",
                subintent="product_search",
                response_policy="answer_from_retrieved_data",
            )

        return _understanding(
            normalized_text=normalized,
            workflow_hypothesis="clarify",
            reason="evaluation_default_clarify",
            intent="clarify",
            response_policy="ask_clarifying_question",
            clarify_question="Could you clarify what you mean?",
        )

    def _build_detail_inference(
        self,
        user_text: str,
        existing_filters: dict[str, str] | None,
    ) -> DetailQueryInferenceResult:
        normalized = normalize_user_text(user_text)
        code = _extract_product_code(user_text)
        existing = {
            str(key or "").strip().lower(): normalize_user_text(value)
            for key, value in dict(existing_filters or {}).items()
            if str(key or "").strip() and str(value or "").strip()
        }
        filters: dict[str, str] = {}
        requested_fields: list[str] = []
        semantic_hints: list[str] = []
        unknown_terms: list[str] = []
        clarify_focus = ""

        if "show me labret" in normalized:
            filters["jewelry_type"] = "labret"
        if "show me gold labret" in normalized:
            filters["jewelry_type"] = "labret"
            filters["material"] = "gold"
        if "what about gold" in normalized or normalized == "gold one":
            filters["material"] = "gold"
        if "show me gld labrt" in normalized:
            filters["jewelry_type"] = "labret"
            filters["material"] = "gold"
        if "opal gold" in normalized:
            filters["material"] = "gold"
        if "sterilization with opal" in normalized:
            semantic_hints = ["sterilization"]
            clarify_focus = "sterilization"
        if "unicorn coating" in normalized:
            filters["jewelry_type"] = "labret"
            unknown_terms = ["unicorn coating"]
            clarify_focus = "unsupported_attribute"
        if code:
            requested_fields = ["sku", "attributes"]
        if normalized in {"show me product info", "product info"} and not existing:
            clarify_focus = "product_anchor"

        wants_image = False
        is_detail = bool(requested_fields or wants_image)
        detail = DetailQuery(
            requested_fields=requested_fields,
            attribute_filters=filters,
            wants_image=wants_image,
            is_detail_request=is_detail,
            semantic_hints=semantic_hints,
            unknown_terms=unknown_terms,
            clarify_focus=clarify_focus,
        )
        return DetailQueryInferenceResult(
            requested_fields=list(detail.requested_fields or []),
            attribute_filters=dict(detail.attribute_filters or {}),
            wants_image=bool(detail.wants_image),
            semantic_hints=list(detail.semantic_hints or []),
            unknown_terms=list(detail.unknown_terms or []),
            clarify_focus=str(detail.clarify_focus or ""),
            confidence=0.95,
            llm_call_count=0,
            debug={},
        )

    async def run_message(self, content: str) -> ChatEvalResult:
        service = ChatService(db=object())
        response = await service.process_chat(
            ChatRequest(user_id=self.user_id, message=content, locale="en-US"),
            channel="widget",
        )
        result = self._build_result(response=response)
        self.turns.append(ChatEvalTurn(user_message=content, response=response, result=result))
        return result

    async def run_messages(self, messages: Sequence[dict[str, str]]) -> ChatEvalResult:
        latest: ChatEvalResult | None = None
        for index, message in enumerate(messages, start=1):
            role = str(message.get("role") or "").strip().lower()
            if role != "user":
                raise ValueError(f"evaluation harness only supports user messages, got {role!r} at turn {index}")
            latest = await self.run_message(str(message.get("content") or ""))
        if latest is None:
            raise ValueError("evaluation harness requires at least one message")
        return latest

    @staticmethod
    def _answer_text_from_response(response: ChatResponse) -> str:
        text = str(response.reply_text or "").strip()
        if text:
            return text
        for component in list(response.components or []):
            raw_type = str(getattr(getattr(component, "type", ""), "value", getattr(component, "type", "")) or "")
            data = dict(getattr(component, "data", {}) or {})
            if raw_type == "assistant_message":
                text = str(data.get("text") or "").strip()
            elif raw_type == "knowledge_answer":
                text = str(data.get("answer") or "").strip()
            elif raw_type in {"clarify", "error"}:
                text = str(data.get("message") or "").strip()
            else:
                text = ""
            if text:
                return text
        return ""

    @staticmethod
    def _normalize_external_filters(filters: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_value in dict(filters or {}).items():
            key = str(raw_key or "").strip().lower()
            value = str(raw_value or "").strip()
            if not key or not value:
                continue
            if key == "jewelry_type":
                key = "product_type"
            if key in {"source_id", "source_raw_sku"}:
                continue
            normalized[key] = value
        return normalized

    @staticmethod
    def _response_component_types(response: ChatResponse) -> list[str]:
        return [
            str(getattr(getattr(component, "type", ""), "value", getattr(component, "type", "")) or "").strip().lower()
            for component in list(response.components or [])
        ]

    @classmethod
    def _infer_internal_workflow_from_response(cls, response: ChatResponse) -> str | None:
        component_types = cls._response_component_types(response)
        if "clarify" in component_types:
            return "clarify"
        if "knowledge_answer" in component_types:
            return "knowledge"
        if "product_detail" in component_types:
            return "product_detail"
        if "product_cards" in component_types:
            return "catalog_search"
        return None

    @staticmethod
    def _find_displayed_product_descriptors(
        *,
        displayed_products: Sequence[dict[str, Any]],
        active_product: dict[str, Any],
    ) -> dict[str, Any]:
        active_product_id = str(active_product.get("product_id") or "").strip()
        active_sku = str(active_product.get("sku") or "").strip().lower()
        active_master_code = str(active_product.get("master_code") or "").strip().lower()
        for item in list(displayed_products or []):
            product_id = str(item.get("product_id") or "").strip()
            sku = str(item.get("sku") or "").strip().lower()
            master_code = str(item.get("master_code") or "").strip().lower()
            if active_product_id and active_product_id == product_id:
                return dict(item.get("descriptors") or {})
            if active_sku and active_sku in {sku, master_code}:
                return dict(item.get("descriptors") or {})
            if active_master_code and active_master_code in {sku, master_code}:
                return dict(item.get("descriptors") or {})
        return {}

    def _build_result(self, *, response: ChatResponse) -> ChatEvalResult:
        component_result = self.last_component_result
        raw_debug = dict(getattr(component_result, "debug", {}) or response.debug or {})
        state = conversation_state.load_state(
            getattr(component_result, "conversation_state", None) or self.current_state
        )
        pending_task = dict(state.get("pending_task") or {})
        active_product = dict(state.get("active_product") or {})
        raw_filters = dict(state.get("last_attribute_filters") or raw_debug.get("merged_attribute_filters") or {})
        active_source = str(active_product.get("source") or "").strip().lower()
        if active_source == "inferred_followup":
            displayed_products = list(state.get("displayed_products") or [])
            descriptors = self._find_displayed_product_descriptors(
                displayed_products=displayed_products,
                active_product=active_product,
            )
            if descriptors:
                raw_filters.setdefault("material", descriptors.get("material"))
                raw_filters.setdefault("jewelry_type", descriptors.get("jewelry_type"))
        product_anchor = (
            str(active_product.get("master_code") or "").strip()
            or str(active_product.get("sku") or "").strip()
            or str(list(raw_debug.get("context_resolved_product_anchor_skus") or [""])[0] or "").strip()
        )
        should_clarify = bool(
            getattr(getattr(response, "routing", None), "needs_clarification", False)
            or any(
                str(getattr(getattr(component, "type", ""), "value", getattr(component, "type", "")) or "").strip()
                == "clarify"
                for component in list(response.components or [])
            )
        )
        pending_task_type = None
        missing_slot = None
        if pending_task:
            pending_task_type = str(pending_task.get("task_type") or "").strip() or None
            missing_slot = str(pending_task.get("missing_slot") or "").strip() or None
        elif not bool(raw_debug.get("pending_task_cleared")):
            pending_task_type = str(raw_debug.get("pending_task_type") or "").strip() or None
            missing_slot = str(raw_debug.get("pending_task_missing_slot") or "").strip() or None
        internal_workflow = str(raw_debug.get("internal_workflow") or "").strip() or self._infer_internal_workflow_from_response(
            response
        )
        return ChatEvalResult(
            answer_text=self._answer_text_from_response(response),
            internal_workflow=internal_workflow or None,
            public_workflow=str(getattr(getattr(response, "routing", None), "workflow", "") or "").strip() or None,
            filters=self._normalize_external_filters(raw_filters),
            should_clarify=should_clarify,
            pending_task_type=pending_task_type,
            missing_slot=missing_slot,
            product_anchor=product_anchor or None,
            conversation_state=state,
            raw_debug=raw_debug,
        )
