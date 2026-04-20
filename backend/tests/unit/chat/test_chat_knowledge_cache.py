from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic_settings")

from app.schemas.chat import KnowledgeSource
from app.services.ai.llm_service import llm_service
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.pipeline_runtime import workflow_knowledge as workflow_knowledge_module


@pytest.mark.asyncio
async def test_knowledge_cache_key_includes_version_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )

    captured: dict[str, object] = {}

    async def fake_generate_embedding(query: str):
        return [0.1, 0.2]

    async def fake_search(*args, **kwargs):
        return [
            KnowledgeSource(
                source_id="src-1",
                chunk_id="chunk-1",
                title="FAQ",
                content_snippet="Example answer",
                category="Policy",
                relevance=0.92,
                url="https://example.com/faq",
                distance=0.08,
            )
        ]

    async def fake_knowledge_answer_once(*args, **kwargs):
        return "direct answer", False

    def fake_stable_cache_key(prefix, payload):
        captured["prefix"] = prefix
        captured["payload"] = payload
        return "cache-key"

    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(pipeline._knowledge_retrieval, "search", fake_search)
    monkeypatch.setattr(pipeline, "_knowledge_answer_once", fake_knowledge_answer_once)
    monkeypatch.setattr(workflow_knowledge_module, "stable_cache_key", fake_stable_cache_key)

    result = await pipeline._resolve_knowledge_payload(
        text="What materials do you use?",
        locale="en-US",
        run_id="run-cache-version",
        store_overview_request=False,
        normalized_text="what materials do you use",
        debug_meta={},
        spans={"vector_search_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert result["knowledge_answer"] == "direct answer"
    assert captured["payload"]["cache_version"] == workflow_knowledge_module.KNOWLEDGE_ANSWER_CACHE_VERSION
