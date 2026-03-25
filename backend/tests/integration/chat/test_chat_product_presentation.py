from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatComponent, ChatRequest, KnowledgeSource, ProductCard
from app.services.ai.llm_service import llm_service
from app.services.chat.routing import routing_policy
from app.services.chat.presentation import product_presentation
from app.services.chat.presentation import component_contract
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.types import ComponentSource, ComponentType
from app.services.chat.runtime import conversation_state


def _canonical_product(*, sku: str, title: str, master_code: str) -> CanonicalProduct:
    return CanonicalProduct(
        product_id=uuid4(),
        sku=sku,
        title=title,
        price=Decimal("10.00"),
        currency="USD",
        in_stock=True,
        stock_qty=5,
        material="Gold",
        gauge="16g",
        image_url="https://example.com/image.jpg",
        description="Sample product",
        attributes={"master_code": master_code, "material": "Gold", "color": "Gold"},
        product_url="https://example.com/product",
    )


def _workflow_decision(
    workflow: str,
    *,
    store_overview_request: bool = False,
    needs_knowledge: bool | None = None,
    knowledge_query: str = "",
) -> routing_policy.WorkflowDecision:
    source = ComponentSource.KNOWLEDGE if workflow == "knowledge" else ComponentSource.SQL
    if workflow == "fallback":
        source = ComponentSource.ERROR
    return routing_policy.WorkflowDecision(
        workflow=workflow,
        source=source,
        needs_products=workflow in {"catalog", "recommendation"},
        needs_knowledge=workflow == "knowledge" if needs_knowledge is None else bool(needs_knowledge),
        needs_clarification=workflow == "fallback",
        store_overview_request=store_overview_request,
        knowledge_query=knowledge_query,
        reason="test_override",
        confidence=1.0,
    )


def test_dedupe_products_by_master_code_counts_unique_masters() -> None:
    products = [
        _canonical_product(sku="A-1", title="Alpha", master_code="ALPHA"),
        _canonical_product(sku="A-2", title="Alpha", master_code="ALPHA"),
        _canonical_product(sku="B-1", title="Beta", master_code="BETA"),
    ]

    deduped, total_unique = product_presentation.dedupe_products_by_master_code(products)

    assert len(deduped) == 2
    assert total_unique == 2


def test_product_presentation_builds_filter_based_copy() -> None:
    reply = product_presentation.build_product_match_reply(
        attribute_filters={"color": "gold", "material": "gold"}
    )
    follow_up = product_presentation.build_see_more_follow_up(
        attribute_filters={"color": "gold", "material": "gold"},
        user_text="I am looking for Gold product",
    )

    assert reply == "I found products that match what you're looking for in Gold color with Gold material."
    assert follow_up == ""


def test_product_presentation_builds_extended_filter_copy() -> None:
    reply = product_presentation.build_product_match_reply(
        attribute_filters={"category": "sterilized", "design": "heart", "jewelry_type": "ring"}
    )
    follow_up = product_presentation.build_see_more_follow_up(
        attribute_filters={"category": "sterilized", "design": "heart", "jewelry_type": "ring"},
        user_text="show sterilized heart rings",
    )

    assert reply == "I found products that match what you're looking for in Sterilized for Ring with Heart design."
    assert follow_up == ""


@pytest.mark.asyncio
async def test_component_pipeline_catalog_pagination_continues_cached_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    products = [
        _canonical_product(
            sku=f"TI-{idx}",
            title=f"Titanium {idx}",
            master_code=f"TI-{idx}",
        )
        for idx in range(1, 13)
    ]
    full_ids = [str(item.product_id) for item in products]
    cache_key = "chat:components:query_ids:pagination-test"

    class _RedisStub:
        async def get_json(self, key):
            if key == cache_key:
                return {
                    "product_ids": list(full_ids),
                    "source": "vector",
                    "result_count": len(full_ids),
                }
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=_RedisStub(),
    )

    async def fake_load_conversation_state(*, conversation_id):
        return {
            "version": conversation_state.CONVERSATION_STATE_VERSION,
            "last_workflow": "catalog",
            "last_refined_query": "Show me titanium jewelry",
            "last_user_query": "Show me titanium jewelry",
            "last_attribute_filters": {"material": "Titanium"},
            "last_requested_fields": [],
            "last_query_cache_key": cache_key,
            "last_result_count": len(full_ids),
            "last_display_offset": 0,
            "last_display_limit": 10,
            "last_product_ids": list(full_ids[:10]),
            "last_product_skus": [item.sku for item in products[:10]],
            "last_currency": "",
            "last_route": "catalog",
            "last_answer_source_ids": [],
            "last_inventory_claim": {
                "sku": "",
                "stock_status": "",
                "last_stock_sync_at": "",
            },
            "tone_recent": [],
            "updated_at": "",
        }

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        selected = [item for item in products if str(item.product_id) in {str(raw) for raw in product_ids}]
        return selected, {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", True, raising=False)
    monkeypatch.setattr(pipeline, "_load_conversation_state", fake_load_conversation_state)
    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="Show more titanium jewelry",
            client_action="catalog_pagination",
            locale="en-US",
        ),
        conversation_id=42,
        run_id="run-pagination",
        route_decision_override=_workflow_decision("catalog"),
    )

    card_ids = [str(card.id) for card in result.response.product_carousel]
    assert card_ids == [str(products[10].product_id), str(products[11].product_id)]
    assert result.debug.get("catalog_pagination_requested") is True
    assert result.debug.get("catalog_pagination_offset") == 10
    assert result.debug.get("catalog_pagination_has_more") is False
    assert not any(
        item.lower().startswith("show more")
        for item in component_contract.follow_up_questions_from_response(result.response)
    )


def test_component_pipeline_build_component_contract_uses_attribute_copy_and_see_more() -> None:
    context = ComponentContext(
        user_text="I am looking for Gold product",
        locale="en-US",
        workflow="catalog",
        query_summary="I am looking for Gold product",
        source=ComponentSource.SQL,
        selected_components=[ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_CARDS],
        canonical_products=[
            _canonical_product(sku="A-1", title="Alpha", master_code="ALPHA"),
            _canonical_product(sku="B-1", title="Beta", master_code="BETA"),
        ],
        result_count=12,
        attribute_filters={"color": "gold", "material": "gold"},
    )
    components = [ChatComponent(type="product_cards", data={"cards": [{}]})]

    payload = ComponentPipeline._build_component_contract(context=context, components=components)
    payload["reply_text"] = str(payload["assistant_text"])

    reply_text = str(payload["reply_text"]).lower()
    assert "gold" in reply_text
    assert ("match" in reply_text) or ("option" in reply_text)
    assert not any(str(item).lower().startswith("see more") for item in payload["follow_up_questions"])
    assert not any("compare" in str(item).lower() for item in payload["follow_up_questions"])
    assert len(payload["product_carousel"]) == 2

    debug_meta: dict[str, object] = {}
    follow_ups = ComponentPipeline._build_conversion_follow_ups(
        products=context.canonical_products,
        attribute_filters=context.attribute_filters,
        user_text=context.user_text,
        needs_knowledge=False,
        result_count=12,
        display_count=10,
        debug_meta=debug_meta,
    )

    assert any(str(item).lower().startswith("show more") for item in follow_ups)
    quick_reply_actions = dict(debug_meta.get("quick_reply_actions") or {})
    assert quick_reply_actions
    assert quick_reply_actions.get("show more gold jewelry", {}).get("action") == "catalog_pagination"


def test_component_pipeline_clarify_policy_for_pagination_exhausted() -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )

    policy = pipeline._build_clarify_policy(
        reason="pagination_exhausted",
        user_text="Show more titanium jewelry",
        tone_pick=lambda _key, variants: str(list(variants or [""])[0]),
        products=[],
        attribute_filters={},
        needs_knowledge=False,
        requested_fields=[],
    )

    assert "last set of matching products" in str(policy.get("message") or "").lower()
    assert policy.get("questions") == ["Which filter should I change next?"]


@pytest.mark.asyncio
async def test_component_pipeline_uses_complementary_mapping_for_recommendation_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = CanonicalProduct(
        product_id=uuid4(),
        sku="LAB-1",
        title="Threadless Labret Post",
        price=Decimal("8.00"),
        currency="USD",
        in_stock=True,
        stock_qty=10,
        material="Titanium",
        gauge="16g",
        image_url=None,
        description="Anchor product",
        attributes={"master_code": "LAB-1", "jewelry_type": "Labret", "threading": "threadless", "gauge": "16g"},
        product_url="https://example.com/labret",
    )
    top = CanonicalProduct(
        product_id=uuid4(),
        sku="TOP-1",
        title="Threadless Heart Top",
        price=Decimal("5.00"),
        currency="USD",
        in_stock=True,
        stock_qty=20,
        material="Titanium",
        gauge="16g",
        image_url=None,
        description="Compatible top",
        attributes={"master_code": "TOP-1", "jewelry_type": "Top", "threading": "threadless", "gauge": "16g"},
        product_url="https://example.com/top",
    )

    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    class _KnowledgeStub:
        async def search(self, *args, **kwargs):
            return []

    class _CatalogStub:
        async def structured_search(self, **kwargs):
            return SimpleNamespace(product_ids=[anchor.product_id]), {}

        async def structured_count(self, **kwargs):
            return 1

        async def vector_search(self, **kwargs):
            card = ProductCard(
                id=top.product_id,
                object_id=top.sku,
                sku=top.sku,
                legacy_sku=[],
                name=top.title,
                description=top.description,
                price=float(top.price),
                currency=top.currency,
                stock_status="in_stock",
                image_url=top.image_url,
                product_url=top.product_url,
                attributes=dict(top.attributes),
            )
            return SimpleNamespace(cards=[card], distance_by_id={str(top.product_id): 0.08})

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        items = []
        for raw in product_ids:
            if str(raw) == str(anchor.product_id):
                items.append(anchor)
            if str(raw) == str(top.product_id):
                items.append(top)
        return items, {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="What goes with this labret?", locale="en-US"),
        conversation_id=42,
        run_id="run-1",
        route_decision_override=_workflow_decision("recommendation"),
    )

    assert result.response.routing.workflow == "recommendation"
    assert result.debug.get("recommendation_mode_requested") == "complementary_items"
    assert result.debug.get("recommendation_expand_source") == "complementary_mapping"
    assert result.debug.get("recommendation_complementary_label") == "Labret tops"
    assert any(component.type.value == "recommendations" for component in result.response.components)


@pytest.mark.asyncio
async def test_component_pipeline_store_overview_request_returns_featured_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labret = CanonicalProduct(
        product_id=uuid4(),
        sku="LAB-1",
        title="Titanium Labret",
        price=Decimal("8.00"),
        currency="USD",
        in_stock=True,
        stock_qty=10,
        material="Titanium",
        gauge="16g",
        image_url=None,
        description="Featured labret",
        attributes={"master_code": "LAB-1", "jewelry_type": "Labret", "material": "Titanium"},
        product_url="https://example.com/labret",
    )
    ring = CanonicalProduct(
        product_id=uuid4(),
        sku="RING-1",
        title="Gold Ring",
        price=Decimal("12.00"),
        currency="USD",
        in_stock=True,
        stock_qty=6,
        material="Gold",
        gauge="18g",
        image_url=None,
        description="Featured ring",
        attributes={"master_code": "RING-1", "jewelry_type": "Ring", "material": "Gold"},
        product_url="https://example.com/ring",
    )

    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=_RedisStub(),
    )

    async def fake_featured_ids(*, limit):
        return [str(labret.product_id), str(ring.product_id)]

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [labret, ring], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(pipeline, "_load_featured_product_ids", fake_featured_ids)
    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(user_id="guest-1", message="What do you have in your store?", locale="en-US"),
        conversation_id=42,
        run_id="run-store-overview",
        route_decision_override=_workflow_decision("catalog", store_overview_request=True),
    )

    assert result.response.routing.workflow == "catalog"
    assert result.debug.get("store_overview_request") is True
    assert "We carry products like" in result.response.reply_text
    assert len(result.response.product_carousel) == 2
    assert any(
        item.startswith("Show ")
        for item in component_contract.follow_up_questions_from_response(result.response)
    )


@pytest.mark.asyncio
async def test_component_pipeline_knowledge_answer_falls_back_when_llm_reply_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=_RedisStub(),
    )

    async def fake_generate_chat_json(*args, **kwargs):
        return {"reply": ""}

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    answer, from_cache = await pipeline._knowledge_answer_once(
        question="What is your return policy?",
        sources=[
            KnowledgeSource(
                source_id="src-1",
                chunk_id="chunk-1",
                title="Returns Policy",
                content_snippet="You can return eligible items within 30 days with approval from the support team.",
                category="Policy",
                relevance=0.9,
                url="https://example.com/returns",
                distance=0.1,
            )
        ],
        locale="en-US",
        store_overview_request=False,
        llm_cache_key="test-key",
    )

    assert from_cache is False
    assert not answer.lower().startswith("here is what i found:")
    assert "return" in answer.lower()


@pytest.mark.asyncio
async def test_component_pipeline_store_overview_knowledge_answer_prefers_structured_contact_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=_RedisStub(),
    )

    async def fake_generate_chat_json(*args, **kwargs):
        return {"reply": "Here is what I found: generic summary"}

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    answer, from_cache = await pipeline._knowledge_answer_once(
        question="Where is your company? I want to buy in person.",
        sources=[
            KnowledgeSource(
                source_id="src-contact",
                chunk_id="chunk-contact",
                title="How can I contact Acha?",
                content_snippet=(
                    "Address: Acha Co., Ltd. 247-249 Tanao Road, Bavornives, Pranakorn, Bangkok 10200, Thailand. "
                    "Email: sales@achadirect.com. Tel: +66 (0)2-629-5858."
                ),
                category="Contact",
                relevance=0.35,
                url="https://www.achadirect.com/faq",
                distance=0.65,
            )
        ],
        locale="en-US",
        store_overview_request=True,
        llm_cache_key="test-store-overview-key",
    )

    assert from_cache is False
    assert "showroom" in answer.lower()
    assert "bangkok" in answer.lower()
    assert ("address" in answer.lower()) or ("contact" in answer.lower())
    assert not answer.lower().startswith("here is what i found:")


@pytest.mark.asyncio
async def test_component_pipeline_knowledge_answer_keeps_long_payment_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=_RedisStub(),
    )

    async def fake_generate_chat_json(*args, **kwargs):
        return {
            "reply": (
                "We accept the following payment methods: "
                "1. PayPal or Credit Card - Fast and convenient for orders under USD 3,000. "
                "2. Bank Transfer - For orders over USD 3,000. "
                "Bank transfers may take 2-5 days for verification. "
                "Please ensure that bank transfer fees are covered."
            )
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    answer, from_cache = await pipeline._knowledge_answer_once(
        question="What payment methods do you accept?",
        sources=[
            KnowledgeSource(
                source_id="src-payment",
                chunk_id="chunk-payment",
                title="Payment Methods",
                content_snippet="We accept credit card, bank transfer, and PayPal.",
                category="Policy",
                relevance=0.95,
                url="https://example.com/payment",
                distance=0.05,
            )
        ],
        locale="en-US",
        store_overview_request=False,
        llm_cache_key="test-payment-key",
    )

    assert from_cache is False
    assert "credit card" in answer.lower()
    assert "bank transfer" in answer.lower()
    assert "fees are covered" in answer.lower()
    assert len(answer) > 240


@pytest.mark.asyncio
async def test_component_pipeline_builds_contextual_show_more_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )

    products = [
        SimpleNamespace(
            sku=f"TI-{idx}",
            attributes={"material": "Titanium", "jewelry_type": "Barbell"},
        )
        for idx in range(1, 13)
    ]

    follow_ups = pipeline._build_show_more_follow_up(
        products=products,
        attribute_filters={"material": "Titanium"},
        result_count=12,
        display_count=10,
        display_offset=0,
    )

    assert any(item.lower().startswith("show more titanium jewelry") for item in follow_ups)


@pytest.mark.asyncio
async def test_component_pipeline_catalog_mixed_intent_adds_knowledge_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _canonical_product(sku="BB-1", title="Steel Barbell", master_code="BB-1")
    source = KnowledgeSource(
        source_id="kb-hours",
        title="Showroom Hours",
        category="Contact",
        content_snippet="Our Bangkok showroom is open Monday to Saturday from 10 AM to 6 PM.",
        relevance=0.92,
        url="https://example.com/hours",
        distance=0.08,
    )

    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    class _KnowledgeStub:
        async def search(self, *args, **kwargs):
            return [source]

    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                product_ids=[str(product.product_id)],
                cards=[],
                distance_by_id={str(product.product_id): 0.08},
                best_distance=0.08,
            )

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_generate_embedding(text: str):
        return [0.1, 0.2, 0.3]

    async def fake_knowledge_answer_once(**kwargs):
        assert "open" in str(kwargs.get("question") or "").lower()
        return "Our Bangkok showroom is open Monday to Saturday, 10 AM to 6 PM.", False

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(pipeline, "_knowledge_answer_once", fake_knowledge_answer_once)

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="I want to buy barbell product and also next week i'm going to thailand when are your store going to open?",
            locale="en-US",
        ),
        conversation_id=42,
        run_id="run-mixed-intent-catalog-knowledge",
        route_decision_override=_workflow_decision(
            "catalog",
            needs_knowledge=True,
            knowledge_query="when is your Thailand showroom open next week",
        ),
    )

    component_types = [component.type.value for component in list(result.response.components or [])]
    assert result.response.routing.workflow == "catalog"
    assert "product_cards" in component_types
    assert "knowledge_answer" in component_types
    assert "barbell" in result.response.reply_text.lower()
    assert "bangkok showroom is open" in result.response.reply_text.lower()
    assert result.response.sources and result.response.sources[0].source_id == "kb-hours"
    assert result.debug.get("mixed_intent_knowledge_used") is True


@pytest.mark.asyncio
async def test_component_pipeline_catalog_mixed_intent_adds_payment_knowledge_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _canonical_product(sku="TI-1", title="Titanium Labret", master_code="TI-1")
    source = KnowledgeSource(
        source_id="kb-payment",
        title="Payment Methods",
        category="Policy",
        content_snippet="We accept credit card, bank transfer, and PayPal.",
        relevance=0.95,
        url="https://example.com/payment",
        distance=0.05,
    )

    class _RedisStub:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl_seconds=0):
            return None

    class _KnowledgeStub:
        async def search(self, *args, **kwargs):
            return [source]

    class _CatalogStub:
        async def structured_count(self, **kwargs):
            return 0

        async def vector_search(self, **kwargs):
            return SimpleNamespace(
                product_ids=[str(product.product_id)],
                cards=[],
                distance_by_id={str(product.product_id): 0.07},
                best_distance=0.07,
            )

    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_RedisStub(),
    )

    async def fake_resolve(*, product_ids, component_types, redis_cache):
        return [product], {"field_union_size": 4, "db_round_trips": 0, "redis_cache_hits": 0}

    async def fake_generate_embedding(text: str):
        return [0.2, 0.3, 0.4]

    async def fake_knowledge_answer_once(**kwargs):
        assert "payment" in str(kwargs.get("question") or "").lower()
        return "We accept credit card, bank transfer, and PayPal.", False

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)
    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(pipeline, "_knowledge_answer_once", fake_knowledge_answer_once)

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="Show me titanium jewelry and also what payment methods do you accept?",
            locale="en-US",
        ),
        conversation_id=43,
        run_id="run-mixed-intent-payment",
        route_decision_override=_workflow_decision(
            "catalog",
            needs_knowledge=True,
            knowledge_query="what payment methods do you accept",
        ),
    )

    component_types = [component.type.value for component in list(result.response.components or [])]
    assert result.response.routing.workflow == "catalog"
    assert "product_cards" in component_types
    assert "knowledge_answer" in component_types
    assert "titanium" in result.response.reply_text.lower()
    assert "bank transfer" in result.response.reply_text.lower()
    assert result.response.sources and result.response.sources[0].source_id == "kb-payment"
    assert result.debug.get("mixed_intent_knowledge_used") is True
