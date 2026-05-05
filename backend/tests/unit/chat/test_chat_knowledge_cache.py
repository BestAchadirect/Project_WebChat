from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic_settings")

from app.schemas.chat import KnowledgeSource
from app.services.ai.llm_service import llm_service
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.pipeline_runtime import workflow_knowledge as workflow_knowledge_module
from app.services.chat.components.pipeline_runtime.state import PipelineWorkflowState


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


@pytest.mark.asyncio
async def test_company_info_payload_returns_structured_clarify_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )

    async def fake_search_company_info_lexical(**kwargs):
        return []

    monkeypatch.setattr(pipeline, "_search_company_info_lexical", fake_search_company_info_lexical)

    result = await pipeline._resolve_company_info_payload(
        text="where is your company located",
        locale="en-US",
        run_id="run-company-clarify",
        store_overview_request=True,
        normalized_text="where is your company located",
        debug_meta={},
        spans={"vector_search_ms": 0.0, "db_product_lookup_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert result["ambiguity_reason"] == "knowledge_needs_clarification"
    assert result["degrade_mode"] == "clarify"


@pytest.mark.asyncio
async def test_company_info_payload_uses_knowledge_unavailable_for_answer_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )

    async def fake_search_company_info_lexical(**kwargs):
        return [
            KnowledgeSource(
                source_id="kb-contact",
                chunk_id="chunk-contact",
                title="Contact",
                content_snippet="Email and phone",
                category="Contact",
                relevance=0.77,
                url="https://example.com/contact",
                distance=0.23,
            )
        ]

    async def fake_attempt_grounded_knowledge_answer(**kwargs):
        return "", pipeline._KNOWLEDGE_UNAVAILABLE_MESSAGE

    monkeypatch.setattr(pipeline, "_search_company_info_lexical", fake_search_company_info_lexical)
    monkeypatch.setattr(pipeline, "_attempt_grounded_knowledge_answer", fake_attempt_grounded_knowledge_answer)

    result = await pipeline._resolve_company_info_payload(
        text="how can I contact your sales team",
        locale="en-US",
        run_id="run-company-unavailable",
        store_overview_request=False,
        normalized_text="how can i contact your sales team",
        debug_meta={},
        spans={"vector_search_ms": 0.0, "db_product_lookup_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert result["ambiguity_reason"] == "knowledge_unavailable"
    assert result["degrade_mode"] == "clarify"


@pytest.mark.asyncio
async def test_knowledge_payload_focuses_sample_sources_before_answer_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )

    captured: dict[str, object] = {}

    async def fake_retrieve_knowledge_sources(**kwargs):
        return (
            [
                KnowledgeSource(
                    source_id="sample-1",
                    chunk_id="chunk-sample",
                    title="Can I sample your products before ordering?",
                    content_snippet="We are happy to provide free product samples to qualified new customers.",
                    category="Samples",
                    relevance=0.74,
                    url="https://example.com/samples",
                    distance=0.26,
                ),
                KnowledgeSource(
                    source_id="contact-1",
                    chunk_id="chunk-contact",
                    title="How can I contact Acha?",
                    content_snippet="Email and phone details for support.",
                    category="Contact",
                    relevance=0.93,
                    url="https://example.com/contact",
                    distance=0.07,
                ),
            ],
            "",
        )

    async def fake_attempt_grounded_knowledge_answer(**kwargs):
        captured["sources"] = [str(source.source_id or "") for source in kwargs.get("knowledge_sources", [])]
        return "We can provide samples for qualified customers.", ""

    monkeypatch.setattr(pipeline, "_retrieve_knowledge_sources", fake_retrieve_knowledge_sources)
    monkeypatch.setattr(pipeline, "_attempt_grounded_knowledge_answer", fake_attempt_grounded_knowledge_answer)

    result = await pipeline._resolve_knowledge_payload(
        text="I want to see the sample first before buying the product. is it ok?",
        locale="en-US",
        run_id="run-knowledge-focus",
        store_overview_request=False,
        normalized_text="i want to see the sample first before buying the product is it ok",
        debug_meta={},
        spans={"vector_search_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert captured["sources"] == ["sample-1"]
    assert [source.source_id for source in result["knowledge_sources"]] == ["sample-1"]
    assert result["knowledge_answer"] == "We can provide samples for qualified customers."
    assert result["ambiguity_reason"] == ""


@pytest.mark.asyncio
async def test_knowledge_answer_rejects_unsupported_factual_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )

    async def fake_generate_chat_json(*args, **kwargs):
        return {
            "reply": (
                "Please contact our Sales Team at sales@company.com or call +1 555 0100."
            )
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)
    debug_meta: dict[str, object] = {}

    answer, from_cache = await pipeline._knowledge_answer_once(
        question="What is the sales email?",
        sources=[
            KnowledgeSource(
                source_id="contact-actual",
                chunk_id="chunk-contact-actual",
                title="How can I contact Acha?",
                content_snippet=(
                    "You can contact Acha by email at sales@achadirect.com "
                    "or phone at +66 (0)2-629-5858."
                ),
                category="Contact",
                relevance=0.95,
                url="https://www.achadirect.com/faq",
                distance=0.05,
            )
        ],
        locale="en-US",
        store_overview_request=False,
        llm_cache_key="test-unsupported-facts",
        debug_meta=debug_meta,
    )

    assert from_cache is False
    assert "sales@achadirect.com" in answer
    assert "sales@company.com" not in answer
    assert "+1 555 0100" not in answer
    assert debug_meta["component_knowledge_answer_rejected"] is True
    assert debug_meta["component_knowledge_answer_rejection_reason"] == "unsupported_factual_claim"
    unsupported = debug_meta["component_knowledge_answer_unsupported_facts"]
    assert "email:sales@company.com" in unsupported


def test_knowledge_fact_validator_allows_supported_facts() -> None:
    unsupported = ComponentPipeline._unsupported_knowledge_facts(
        answer=(
            "Contact sales@achadirect.com or call +66 (0)2-629-5858. "
            "Returns are available within 30 days."
        ),
        sources=[
            KnowledgeSource(
                source_id="contact-and-returns",
                chunk_id="chunk-contact-and-returns",
                title="Contact and returns",
                content_snippet=(
                    "Email sales@achadirect.com, phone +66 (0)2-629-5858, "
                    "and returns within 30 days are supported."
                ),
                category="Contact",
                relevance=0.94,
                url="https://www.achadirect.com/faq",
                distance=0.06,
            )
        ],
    )

    assert unsupported == []


@pytest.mark.asyncio
async def test_mixed_knowledge_enrichment_skips_when_state_already_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )
    state = PipelineWorkflowState()
    state.decision.ambiguity_reason = "catalog_no_results"
    debug_meta: dict[str, object] = {}

    async def fake_resolve_knowledge_payload(**kwargs):
        return {
            "knowledge_query": "shipping policy",
            "knowledge_sources": [
                KnowledgeSource(
                    source_id="src-1",
                    chunk_id="chunk-1",
                    title="Shipping Policy",
                    content_snippet="Shipping details",
                    category="Policy",
                    relevance=0.91,
                    url="https://example.com/shipping",
                    distance=0.09,
                )
            ],
            "knowledge_answer": "We ship internationally.",
            "knowledge_error_message": "",
            "knowledge_is_high_risk": False,
            "knowledge_sources_weak": False,
            "min_knowledge_relevance": 0.4,
            "top_knowledge_relevance": 0.91,
            "skip_knowledge_answer": False,
            "ambiguity_reason": "",
            "degrade_mode": "answer",
        }

    monkeypatch.setattr(pipeline, "_resolve_knowledge_payload", fake_resolve_knowledge_payload)

    await pipeline._handle_mixed_knowledge_enrichment(
        state=state,
        text="and what is your shipping policy?",
        locale="en-US",
        run_id="run-mixed-skip",
        store_overview_request=False,
        normalized_text="and what is your shipping policy",
        debug_meta=debug_meta,
        spans={"vector_search_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert state.knowledge.answer == ""
    assert debug_meta["mixed_intent_knowledge_used"] is False
