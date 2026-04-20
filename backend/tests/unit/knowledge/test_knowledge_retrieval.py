from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import KnowledgeSource
from app.services.knowledge.retrieval import KnowledgeRetrievalService


@pytest.mark.asyncio
async def test_search_broadens_category_queries_and_returns_stable_sorted_matches() -> None:
    service = KnowledgeRetrievalService(db=object())
    captured: dict[str, object] = {}

    async def fake_search_knowledge(*, query_text, query_embedding, limit, **kwargs):
        captured["limit"] = limit
        return (
            [
                KnowledgeSource(
                    source_id="c",
                    title="Contact us",
                    content_snippet="Reach our team.",
                    category=" Contact ",
                    relevance=0.55,
                    url="https://example.com/contact",
                ),
                KnowledgeSource(
                    source_id="a",
                    title="Shipping policy",
                    content_snippet="Shipping details.",
                    category="Policy",
                    relevance=0.91,
                    url="https://example.com/shipping",
                ),
                KnowledgeSource(
                    source_id="b",
                    title="Returns policy",
                    content_snippet="Returns details.",
                    category="policy",
                    relevance=0.75,
                    url="https://example.com/returns",
                ),
            ],
            0.09,
        )

    service._pipeline.search_knowledge = fake_search_knowledge  # type: ignore[attr-defined]

    results = await service.search(
        query_text="what is your policy?",
        query_embedding=[0.1, 0.2],
        limit=2,
        category=" Policy ",
    )

    assert captured["limit"] == 10
    assert [item.source_id for item in results] == ["a", "b"]

