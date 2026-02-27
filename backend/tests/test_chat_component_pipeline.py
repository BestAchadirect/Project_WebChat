from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.schemas.chat import ChatRequest, KnowledgeSource
from app.services.ai.llm_service import llm_service
from app.services.catalog.product_search import ProductSearchResult
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.pipeline import ComponentPipeline


class _MemoryRedisCache:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    async def get_json(self, key: str):
        return self._store.get(key)

    async def set_json(self, key: str, payload: dict, ttl_seconds: int) -> None:
        self._store[key] = dict(payload)


class _CatalogStub:
    def __init__(self, *, structured_ids=None, vector_ids=None):
        self.structured_ids = list(structured_ids or [])
        self.vector_ids = list(vector_ids or [])
        self.structured_calls = 0
        self.structured_count_calls = 0
        self.smart_calls = 0

    async def structured_search(
        self,
        *,
        sku_token,
        attribute_filters,
        limit=10,
        candidate_cap=None,
        catalog_version=None,
        return_ids_only=False,
    ):
        self.structured_calls += 1
        return (
            ProductSearchResult(
                cards=[],
                distances=[],
                best_distance=None,
                distance_by_id={},
                product_ids=list(self.structured_ids),
            ),
            {
                "structured_read_mode": "projection",
                "projection_hit": bool(self.structured_ids),
            },
        )

    async def structured_count(self, *, sku_token, attribute_filters):
        self.structured_count_calls += 1
        return len(self.structured_ids)

    async def smart_search(self, *, query_embedding, candidates, limit=10):
        self.smart_calls += 1
        return ProductSearchResult(
            cards=[],
            distances=[],
            best_distance=None,
            distance_by_id={},
            product_ids=list(self.vector_ids),
        )


class _KnowledgeStub:
    def __init__(self, *, sources=None):
        self.sources = list(sources or [])
        self.calls = 0

    async def search(self, *, query_text, query_embedding, limit=5, run_id=None):
        self.calls += 1
        return list(self.sources)


def _canonical_product(product_id):
    return CanonicalProduct(
        product_id=product_id,
        sku="SKU-1",
        title="Ring One",
        price=Decimal("10.00"),
        currency="USD",
        in_stock=True,
        stock_qty=3,
        material="Steel",
        gauge="16g",
        image_url="https://example.com/1.jpg",
        attributes={"material": "Steel", "gauge": "16g"},
        product_url="https://example.com/p1",
    )


@pytest.mark.asyncio
async def test_pipeline_product_sql_hit_skips_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    product_id = uuid4()
    catalog = _CatalogStub(structured_ids=[product_id], vector_ids=[])
    pipeline = ComponentPipeline(
        db=object(),  # not used because resolver is monkeypatched
        catalog_search=catalog,  # type: ignore[arg-type]
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_MemoryRedisCache(),  # type: ignore[arg-type]
    )

    async def fake_resolve(**kwargs):
        return (
            [_canonical_product(product_id)],
            {"field_union_size": 3, "enrichment_used": False, "db_round_trips": 1, "redis_cache_hits": 0},
        )

    async def should_not_embed(*args, **kwargs):
        raise AssertionError("embedding should not run on SQL hit")

    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)
    monkeypatch.setattr(llm_service, "generate_embedding", should_not_embed)

    result = await pipeline.run(
        request=ChatRequest(user_id="u1", message="show products", locale="en-US"),
        conversation_id=1,
        run_id="run-1",
    )

    assert result.embedding_calls == 0
    assert result.llm_calls == 0
    assert catalog.structured_calls >= 1
    assert catalog.smart_calls == 0
    assert any(component.type.value == "product_cards" for component in result.response.components)


@pytest.mark.asyncio
async def test_pipeline_sql_miss_vector_fallback_uses_single_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    product_id = uuid4()
    catalog = _CatalogStub(structured_ids=[], vector_ids=[product_id])
    pipeline = ComponentPipeline(
        db=object(),  # not used because resolver is monkeypatched
        catalog_search=catalog,  # type: ignore[arg-type]
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_MemoryRedisCache(),  # type: ignore[arg-type]
    )

    embed_calls = {"count": 0}

    async def fake_embedding(text: str):
        embed_calls["count"] += 1
        return [0.1, 0.2]

    async def fake_resolve(**kwargs):
        return (
            [_canonical_product(product_id)],
            {"field_union_size": 3, "enrichment_used": False, "db_round_trips": 1, "redis_cache_hits": 0},
        )

    monkeypatch.setattr(llm_service, "generate_embedding", fake_embedding)
    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(user_id="u2", message="suggest something minimal", locale="en-US"),
        conversation_id=2,
        run_id="run-2",
    )

    assert embed_calls["count"] == 1
    assert result.embedding_calls == 1
    assert catalog.smart_calls == 1
    assert result.debug.get("component_source") == "vector"


@pytest.mark.asyncio
async def test_pipeline_exact_sku_miss_does_not_trigger_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _CatalogStub(structured_ids=[], vector_ids=[uuid4()])
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=catalog,  # type: ignore[arg-type]
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_MemoryRedisCache(),  # type: ignore[arg-type]
    )

    async def should_not_embed(*args, **kwargs):
        raise AssertionError("embedding should not run for exact SKU miss")

    async def fake_resolve(**kwargs):
        return [], {"field_union_size": 0, "enrichment_used": False, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(llm_service, "generate_embedding", should_not_embed)
    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(user_id="u3", message="tell me about SKU-123", locale="en-US"),
        conversation_id=3,
        run_id="run-3",
    )

    assert result.embedding_calls == 0
    assert catalog.smart_calls == 0
    assert any(component.type.value == "clarify" for component in result.response.components)


@pytest.mark.asyncio
async def test_pipeline_compare_without_two_skus_returns_clarify() -> None:
    catalog = _CatalogStub(structured_ids=[uuid4()])
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=catalog,  # type: ignore[arg-type]
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_MemoryRedisCache(),  # type: ignore[arg-type]
    )

    result = await pipeline.run(
        request=ChatRequest(user_id="u5", message="compare SKU-123", locale="en-US"),
        conversation_id=5,
        run_id="run-5",
    )

    assert any(component.type.value == "clarify" for component in result.response.components)
    assert catalog.structured_calls == 0


@pytest.mark.asyncio
async def test_pipeline_knowledge_path_uses_single_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    knowledge = _KnowledgeStub(
        sources=[
            KnowledgeSource(
                source_id="kb-1",
                title="Shipping policy",
                content_snippet="Shipping is 3-5 business days.",
                relevance=0.92,
            )
        ]
    )
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=knowledge,  # type: ignore[arg-type]
        redis_cache=_MemoryRedisCache(),  # type: ignore[arg-type]
    )

    embed_calls = {"count": 0}
    chat_calls = {"count": 0}

    async def fake_embedding(text: str):
        embed_calls["count"] += 1
        return [0.2, 0.3]

    async def fake_generate_chat_json(messages, model=None, temperature=0.2, usage_kind=None):
        chat_calls["count"] += 1
        return {"reply": "Shipping takes 3-5 business days."}

    monkeypatch.setattr(llm_service, "generate_embedding", fake_embedding)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    result = await pipeline.run(
        request=ChatRequest(user_id="u4", message="what is your shipping policy?", locale="en-US"),
        conversation_id=4,
        run_id="run-4",
    )

    assert embed_calls["count"] == 1
    assert chat_calls["count"] == 1
    assert result.embedding_calls == 1
    assert result.llm_calls == 1
    assert any(component.type.value == "knowledge_answer" for component in result.response.components)


@pytest.mark.asyncio
async def test_pipeline_hyphenated_words_are_not_treated_as_sku(monkeypatch: pytest.MonkeyPatch) -> None:
    knowledge = _KnowledgeStub(
        sources=[
            KnowledgeSource(
                source_id="kb-2",
                title="Language Support",
                content_snippet="Support available in French, German, Spanish, and Thai.",
                relevance=0.8,
            )
        ]
    )
    catalog = _CatalogStub(structured_ids=[uuid4()])
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=catalog,  # type: ignore[arg-type]
        knowledge_retrieval=knowledge,  # type: ignore[arg-type]
        redis_cache=_MemoryRedisCache(),  # type: ignore[arg-type]
    )

    async def fake_embedding(text: str):
        return [0.3, 0.4]

    async def fake_generate_chat_json(messages, model=None, temperature=0.2, usage_kind=None):
        return {"reply": "We can support French as well."}

    async def fake_resolve(**kwargs):
        return [], {"field_union_size": 0, "enrichment_used": False, "db_round_trips": 0, "redis_cache_hits": 0}

    monkeypatch.setattr(llm_service, "generate_embedding", fake_embedding)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)
    monkeypatch.setattr(pipeline._field_resolver, "resolve", fake_resolve)

    result = await pipeline.run(
        request=ChatRequest(user_id="u6", message="Je ne parle pas anglais. Pouvez-vous m'aider?", locale="fr-FR"),
        conversation_id=6,
        run_id="run-6",
    )

    assert result.response.intent == "knowledge_query"
    assert catalog.structured_calls == 0
    assert any(component.type.value == "knowledge_answer" for component in result.response.components)


@pytest.mark.asyncio
async def test_pipeline_knowledge_embedding_failure_fails_soft_to_error_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=_CatalogStub(),
        knowledge_retrieval=_KnowledgeStub(),  # type: ignore[arg-type]
        redis_cache=_MemoryRedisCache(),  # type: ignore[arg-type]
    )

    async def fail_embedding(text: str):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(llm_service, "generate_embedding", fail_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="u7", message="what is your shipping policy?", locale="en-US"),
        conversation_id=7,
        run_id="run-7",
    )

    assert result.response.intent == "knowledge_query"
    assert result.llm_calls == 0
    assert result.debug.get("component_knowledge_fail_soft") is True
    assert any(component.type.value == "error" for component in result.response.components)


@pytest.mark.asyncio
async def test_pipeline_product_vector_embedding_failure_returns_clarify(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _CatalogStub(structured_ids=[], vector_ids=[uuid4()])
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=catalog,  # type: ignore[arg-type]
        knowledge_retrieval=_KnowledgeStub(),
        redis_cache=_MemoryRedisCache(),  # type: ignore[arg-type]
    )

    async def fail_embedding(text: str):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(llm_service, "generate_embedding", fail_embedding)

    result = await pipeline.run(
        request=ChatRequest(user_id="u8", message="find me minimal steel ring", locale="en-US"),
        conversation_id=8,
        run_id="run-8",
    )

    assert result.embedding_calls == 0
    assert catalog.smart_calls == 0
    assert result.debug.get("component_vector_fallback_skipped") is True
    assert any(component.type.value == "clarify" for component in result.response.components)
