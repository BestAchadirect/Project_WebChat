from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import KnowledgeSource
from app.services.knowledge.pipeline import KnowledgePipeline


def _source(
    *,
    title: str,
    category: str,
    snippet: str,
    distance: float,
    url: str = "https://www.example.com/faq",
) -> KnowledgeSource:
    return KnowledgeSource(
        source_id=title.lower().replace(" ", "-"),
        title=title,
        category=category,
        url=url,
        content_snippet=snippet,
        relevance=1.0 - distance,
        distance=distance,
    )


def test_store_profile_rerank_is_noop_for_store_overview_query() -> None:
    sources = [
        _source(
            title="Can I sample your products before ordering?",
            category="Samples",
            snippet="We can provide free product samples.",
            distance=0.65,
        ),
        _source(
            title="Do you have a Money Back Guarantee?",
            category="Refunds",
            snippet="We offer refunds under our return policy.",
            distance=0.70,
        ),
        _source(
            title="How can I contact Acha?",
            category="Contact",
            snippet="Acha Co., Ltd. showroom address in Bangkok with phone and email details.",
            distance=0.72,
        ),
        _source(
            title="Can you supply references in my country?",
            category="Trust & Compliance",
            snippet="Our main showroom is in Bangkok.",
            distance=0.63,
        ),
    ]

    ranked = KnowledgePipeline._rerank_sources_for_store_profile(
        sources=sources,
        query_text="where is your company? I want to buy in person",
        store_overview_request=True,
    )

    assert [item.title for item in ranked] == [item.title for item in sources]


def test_store_profile_rerank_is_noop_for_generic_policy_query() -> None:
    sources = [
        _source(
            title="What is your shipping policy?",
            category="Shipping",
            snippet="Shipping takes 3-5 business days.",
            distance=0.22,
        ),
        _source(
            title="How can I contact Acha?",
            category="Contact",
            snippet="Contact us by email or phone.",
            distance=0.45,
        ),
    ]

    ranked = KnowledgePipeline._rerank_sources_for_store_profile(
        sources=sources,
        query_text="What is your shipping policy?",
        store_overview_request=False,
    )

    assert [item.title for item in ranked] == [item.title for item in sources]


def test_store_profile_rerank_is_noop_for_store_overview_request() -> None:
    sources = [
        _source(
            title="Custom Manufactured Items",
            category="Custom Orders",
            snippet="We welcome custom jewelry requests.",
            distance=0.28,
        ),
        _source(
            title="What is your minimum order?",
            category="Ordering",
            snippet="USD 150 for standard website orders.",
            distance=0.12,
        ),
    ]

    ranked = KnowledgePipeline._rerank_sources_for_store_profile(
        sources=sources,
        query_text="Do you offer custom designs?",
        store_overview_request=True,
    )

    assert [item.title for item in ranked] == [item.title for item in sources]


@pytest.mark.asyncio
async def test_search_knowledge_propagates_summary_text_into_sources() -> None:
    article_id = uuid4()
    chunk_id = uuid4()

    class _FakeResult:
        def all(self):
            return [
                (
                    1,
                    "Shipping details are available in the FAQ body.",
                    article_id,
                    chunk_id,
                    "Shipping Policy",
                    "Shipping",
                    "https://www.example.com/shipping",
                    "Orders usually arrive within 3-5 business days.",
                    0.27,
                )
            ]

    class _FakeDB:
        async def execute(self, stmt):
            return _FakeResult()

    pipeline = KnowledgePipeline(db=_FakeDB(), log_event=lambda *args, **kwargs: None)

    sources, best_distance = await pipeline.search_knowledge(
        "what is your shipping policy",
        [0.1, 0.2, 0.3],
        limit=1,
        must_tags=None,
        boost_tags=None,
        store_overview_request=False,
        run_id=None,
    )

    assert best_distance == 0.27
    assert len(sources) == 1
    assert sources[0].summary == "Orders usually arrive within 3-5 business days."
    assert sources[0].content_snippet == "Shipping details are available in the FAQ body."
