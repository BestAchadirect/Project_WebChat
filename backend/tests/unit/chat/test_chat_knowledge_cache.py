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

    async def fake_plan_knowledge_retrieval(**kwargs):
        return {
            "query_text": "What materials do you use?",
            "topic": "products",
            "must_tags": [],
            "boost_tags": [],
            "required_evidence": ["materials"],
            "forbidden_topics": [],
            "store_overview_request": False,
            "answer_style": {"max_sentences": 2},
        }

    async def fake_select_knowledge_sources_with_llm(**kwargs):
        return list(kwargs.get("candidates", []) or [])[:3]

    def fake_stable_cache_key(prefix, payload):
        captured["prefix"] = prefix
        captured["payload"] = payload
        return "cache-key"

    monkeypatch.setattr(llm_service, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(pipeline._knowledge_retrieval, "search", fake_search)
    monkeypatch.setattr(pipeline, "_knowledge_answer_once", fake_knowledge_answer_once)
    monkeypatch.setattr(pipeline, "_plan_knowledge_retrieval", fake_plan_knowledge_retrieval)
    monkeypatch.setattr(pipeline, "_select_knowledge_sources_with_llm", fake_select_knowledge_sources_with_llm)
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

    async def fake_plan_company_info_retrieval(**kwargs):
        return {
            "query_text": "company location",
            "topic": "store_overview",
            "must_tags": ["store_overview"],
            "boost_tags": ["contact"],
            "store_overview_request": True,
            "required_evidence": ["company location"],
            "forbidden_topics": [],
            "answer_style": {"max_sentences": 2},
        }

    monkeypatch.setattr(pipeline, "_search_company_info_lexical", fake_search_company_info_lexical)
    monkeypatch.setattr(pipeline, "_plan_company_info_retrieval", fake_plan_company_info_retrieval)

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

    async def fake_plan_company_info_retrieval(**kwargs):
        return {
            "query_text": "contact sales team",
            "topic": "contact",
            "must_tags": ["contact"],
            "boost_tags": ["contact", "support"],
            "store_overview_request": False,
            "required_evidence": ["sales contact"],
            "forbidden_topics": [],
            "answer_style": {"max_sentences": 2},
        }

    async def fake_select_company_info_sources_with_llm(**kwargs):
        return list(kwargs.get("candidates", []) or [])[:3]

    monkeypatch.setattr(pipeline, "_search_company_info_lexical", fake_search_company_info_lexical)
    monkeypatch.setattr(pipeline, "_attempt_grounded_knowledge_answer", fake_attempt_grounded_knowledge_answer)
    monkeypatch.setattr(pipeline, "_plan_company_info_retrieval", fake_plan_company_info_retrieval)
    monkeypatch.setattr(pipeline, "_select_company_info_sources_with_llm", fake_select_company_info_sources_with_llm)

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
async def test_company_info_payload_uses_llm_plan_and_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )

    captured: dict[str, object] = {}
    contact_source = KnowledgeSource(
        source_id="contact-src",
        chunk_id="contact-chunk",
        title="How can I contact Acha?",
        content_snippet="Email sales@achadirect.com or call +66 (0)2-629-5858.",
        category="Contact",
        relevance=0.94,
        url="https://www.achadirect.com/faq",
        distance=0.06,
    )
    refund_source = KnowledgeSource(
        source_id="refund-src",
        chunk_id="refund-chunk",
        title="Do you have a Money Back Guarantee?",
        content_snippet="Contact us for an RMA before returning products.",
        category="Refunds",
        relevance=0.91,
        url="https://www.achadirect.com/faq",
        distance=0.09,
    )

    async def fake_generate_chat_json(*args, **kwargs):
        usage_kind = kwargs.get("usage_kind")
        if usage_kind == "company_info_retrieval_plan":
            return {
                "retrieval_query": "sales contact email phone showroom",
                "topic": "contact",
                "must_tags": ["contact"],
                "boost_tags": ["contact", "support"],
                "required_evidence": ["email", "phone"],
                "forbidden_topics": ["refunds", "returns", "taxes"],
                "store_overview_request": False,
                "answer_style": {"max_sentences": 2},
            }
        if usage_kind == "company_info_evidence_select":
            return {
                "answerable": True,
                "selected_source_ids": ["contact-src"],
                "rejected": ["refund-src"],
                "missing_evidence": [],
                "reason": "The contact source directly answers the contact question.",
            }
        raise AssertionError(f"unexpected usage_kind: {usage_kind}")

    async def fake_search_company_info_lexical(**kwargs):
        captured["query_text"] = kwargs.get("query_text")
        captured["must_tags"] = kwargs.get("must_tags")
        return [refund_source, contact_source]

    async def fake_attempt_grounded_knowledge_answer(**kwargs):
        sources = list(kwargs.get("knowledge_sources", []) or [])
        captured["answer_source_ids"] = [str(source.source_id or "") for source in sources]
        return "You can contact Acha at sales@achadirect.com or +66 (0)2-629-5858.", ""

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)
    monkeypatch.setattr(pipeline, "_search_company_info_lexical", fake_search_company_info_lexical)
    monkeypatch.setattr(pipeline, "_attempt_grounded_knowledge_answer", fake_attempt_grounded_knowledge_answer)

    debug_meta: dict[str, object] = {}
    result = await pipeline._resolve_company_info_payload(
        text="How can i contact you",
        locale="en-US",
        run_id="run-company-llm-selector",
        store_overview_request=False,
        normalized_text="how can i contact you",
        debug_meta=debug_meta,
        spans={"vector_search_ms": 0.0, "db_product_lookup_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert captured["query_text"] == "sales contact email phone showroom"
    assert captured["must_tags"] == ["contact"]
    assert captured["answer_source_ids"] == ["contact-src"]
    assert [source.source_id for source in result["knowledge_sources"]] == ["contact-src"]
    assert result["knowledge_answer"] == "You can contact Acha at sales@achadirect.com or +66 (0)2-629-5858."
    assert result["ambiguity_reason"] == ""
    assert debug_meta["company_info_plan_source"] == "llm"
    assert debug_meta["company_info_selector_source"] == "llm"


@pytest.mark.asyncio
async def test_company_info_payload_falls_back_to_retrieved_sources_when_selector_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )
    contact_source = KnowledgeSource(
        source_id="contact-src",
        chunk_id="contact-chunk",
        title="How can I contact Acha?",
        content_snippet="Email sales@achadirect.com or call +66 (0)2-629-5858.",
        category="Contact",
        relevance=0.94,
        url="https://www.achadirect.com/faq",
        distance=0.06,
    )
    captured: dict[str, object] = {}

    async def fake_plan_company_info_retrieval(**kwargs):
        return {
            "query_text": "customer contact email phone showroom",
            "topic": "contact",
            "must_tags": [],
            "boost_tags": ["contact"],
            "store_overview_request": False,
            "required_evidence": ["contact details"],
            "forbidden_topics": [],
            "answer_style": {"max_sentences": 2},
        }

    async def fake_search_company_info_lexical(**kwargs):
        return [contact_source]

    async def fake_select_company_info_sources_with_llm(**kwargs):
        debug_meta = kwargs["debug_meta"]
        debug_meta["company_info_selector_source"] = "unavailable"
        debug_meta["company_info_selector_error"] = "LLM JSON response truncated before content"
        return []

    async def fake_attempt_grounded_knowledge_answer(**kwargs):
        captured["answer_source_ids"] = [
            str(source.source_id or "") for source in list(kwargs.get("knowledge_sources", []) or [])
        ]
        return "You can contact Acha at sales@achadirect.com or +66 (0)2-629-5858.", ""

    monkeypatch.setattr(pipeline, "_plan_company_info_retrieval", fake_plan_company_info_retrieval)
    monkeypatch.setattr(pipeline, "_search_company_info_lexical", fake_search_company_info_lexical)
    monkeypatch.setattr(pipeline, "_select_company_info_sources_with_llm", fake_select_company_info_sources_with_llm)
    monkeypatch.setattr(pipeline, "_attempt_grounded_knowledge_answer", fake_attempt_grounded_knowledge_answer)

    debug_meta: dict[str, object] = {}
    result = await pipeline._resolve_company_info_payload(
        text="How can I contact you?",
        locale="en-US",
        run_id="run-company-selector-fallback",
        store_overview_request=False,
        normalized_text="how can i contact you",
        debug_meta=debug_meta,
        spans={"vector_search_ms": 0.0, "db_product_lookup_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert captured["answer_source_ids"] == ["contact-src"]
    assert [source.source_id for source in result["knowledge_sources"]] == ["contact-src"]
    assert result["knowledge_answer"] == "You can contact Acha at sales@achadirect.com or +66 (0)2-629-5858."
    assert result["ambiguity_reason"] == ""
    assert debug_meta["company_info_selector_fallback_used"] is True
    assert debug_meta["company_info_source_count_after_selector"] == 1


@pytest.mark.asyncio
async def test_company_info_retrieval_broadens_over_strict_llm_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )
    contact_source = KnowledgeSource(
        source_id="contact-src",
        chunk_id="contact-chunk",
        title="How can I contact Acha?",
        content_snippet="Email sales@achadirect.com.",
        category="Contact",
        relevance=0.95,
        url="https://www.achadirect.com/faq",
        distance=0.05,
    )
    calls: list[dict[str, object]] = []

    async def fake_search_company_info_lexical(**kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("must_tags"):
            return []
        return [contact_source]

    monkeypatch.setattr(pipeline, "_search_company_info_lexical", fake_search_company_info_lexical)

    debug_meta: dict[str, object] = {}
    result = await pipeline._retrieve_company_info_sources(
        query_text="customer contact support email phone",
        must_tags=["contact", "support"],
        boost_tags=["contact"],
        limit=12,
        store_overview_request=False,
        run_id="run-company-broaden",
        debug_meta=debug_meta,
        spans={"vector_search_ms": 0.0, "db_product_lookup_ms": 0.0},
        external_call_counts={},
    )

    assert [source.source_id for source in result] == ["contact-src"]
    assert calls[0]["must_tags"] == ["contact", "support"]
    assert calls[1]["must_tags"] == []
    assert calls[1]["boost_tags"] == ["contact", "support"]
    assert debug_meta["component_company_info_broadened_strict_tags"] is True


@pytest.mark.asyncio
async def test_knowledge_payload_uses_llm_selector_before_answer_generation(
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

    async def fake_plan_knowledge_retrieval(**kwargs):
        return {
            "query_text": "can I get product samples before buying",
            "topic": "samples",
            "must_tags": [],
            "boost_tags": ["samples"],
            "required_evidence": ["sample availability"],
            "forbidden_topics": ["general contact"],
            "store_overview_request": False,
            "answer_style": {"max_sentences": 2},
        }

    async def fake_select_knowledge_sources_with_llm(**kwargs):
        captured["selector_candidates"] = [
            str(source.source_id or "") for source in list(kwargs.get("candidates", []) or [])
        ]
        return [
            source
            for source in list(kwargs.get("candidates", []) or [])
            if str(source.source_id or "") == "sample-1"
        ]

    async def fake_attempt_grounded_knowledge_answer(**kwargs):
        captured["sources"] = [str(source.source_id or "") for source in kwargs.get("knowledge_sources", [])]
        return "We can provide samples for qualified customers.", ""

    monkeypatch.setattr(pipeline, "_retrieve_knowledge_sources", fake_retrieve_knowledge_sources)
    monkeypatch.setattr(pipeline, "_plan_knowledge_retrieval", fake_plan_knowledge_retrieval)
    monkeypatch.setattr(pipeline, "_select_knowledge_sources_with_llm", fake_select_knowledge_sources_with_llm)
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

    assert captured["selector_candidates"] == ["sample-1", "contact-1"]
    assert captured["sources"] == ["sample-1"]
    assert [source.source_id for source in result["knowledge_sources"]] == ["sample-1"]
    assert result["knowledge_answer"] == "We can provide samples for qualified customers."
    assert result["ambiguity_reason"] == ""


@pytest.mark.asyncio
async def test_knowledge_payload_falls_back_to_retrieved_sources_when_selector_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )
    stock_source = KnowledgeSource(
        source_id="stock-src",
        chunk_id="stock-chunk",
        title="What if the item I ordered is out of stock?",
        content_snippet="If an ordered item is out of stock, the Sales Team will contact you with available options.",
        category="Stock",
        relevance=0.82,
        url="https://example.com/stock",
        distance=0.18,
    )
    captured: dict[str, object] = {}

    async def fake_retrieve_knowledge_sources(**kwargs):
        return [stock_source], ""

    async def fake_plan_knowledge_retrieval(**kwargs):
        return {
            "query_text": "what happens if an ordered item is out of stock",
            "topic": "stock",
            "must_tags": [],
            "boost_tags": ["stock"],
            "required_evidence": ["out-of-stock process"],
            "forbidden_topics": [],
            "store_overview_request": False,
            "answer_style": {"max_sentences": 2},
        }

    async def fake_select_knowledge_sources_with_llm(**kwargs):
        debug_meta = kwargs["debug_meta"]
        debug_meta["knowledge_selector_source"] = "unavailable"
        debug_meta["knowledge_selector_error"] = "LLM JSON response truncated before content"
        return []

    async def fake_attempt_grounded_knowledge_answer(**kwargs):
        captured["answer_source_ids"] = [
            str(source.source_id or "") for source in list(kwargs.get("knowledge_sources", []) or [])
        ]
        return "If an ordered item is out of stock, the Sales Team will contact you with available options.", ""

    monkeypatch.setattr(pipeline, "_retrieve_knowledge_sources", fake_retrieve_knowledge_sources)
    monkeypatch.setattr(pipeline, "_plan_knowledge_retrieval", fake_plan_knowledge_retrieval)
    monkeypatch.setattr(pipeline, "_select_knowledge_sources_with_llm", fake_select_knowledge_sources_with_llm)
    monkeypatch.setattr(pipeline, "_attempt_grounded_knowledge_answer", fake_attempt_grounded_knowledge_answer)

    debug_meta: dict[str, object] = {}
    result = await pipeline._resolve_knowledge_payload(
        text="What if the item I ordered is out of stock?",
        locale="en-US",
        run_id="run-knowledge-selector-fallback",
        store_overview_request=False,
        normalized_text="what if the item i ordered is out of stock",
        debug_meta=debug_meta,
        spans={"vector_search_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert captured["answer_source_ids"] == ["stock-src"]
    assert [source.source_id for source in result["knowledge_sources"]] == ["stock-src"]
    assert result["knowledge_answer"].startswith("If an ordered item is out of stock")
    assert result["ambiguity_reason"] == ""
    assert debug_meta["knowledge_selector_fallback_used"] is True
    assert debug_meta["knowledge_source_count_after_selector"] == 1


@pytest.mark.asyncio
async def test_knowledge_payload_enriches_contact_source_for_return_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )
    refund_source = KnowledgeSource(
        source_id="refund-src",
        chunk_id="refund-chunk",
        title="Refund Policy",
        content_snippet="Contact us within 30 days to obtain an RMA before returning the item.",
        category="Refunds",
        relevance=0.93,
        url="https://example.com/refunds",
        distance=0.07,
    )
    contact_source = KnowledgeSource(
        source_id="contact-src",
        chunk_id="contact-chunk",
        title="How can I contact Acha?",
        content_snippet="Email sales@achadirect.com or call +66 (0)2-629-5858.",
        category="Contact",
        relevance=0.96,
        url="https://example.com/contact",
        distance=0.04,
    )
    captured: dict[str, object] = {}

    async def fake_retrieve_knowledge_sources(**kwargs):
        return [refund_source], ""

    async def fake_plan_knowledge_retrieval(**kwargs):
        return {
            "query_text": "wrong item refund return replacement",
            "topic": "refunds",
            "must_tags": [],
            "boost_tags": ["refunds"],
            "required_evidence": ["refund eligibility", "rma"],
            "forbidden_topics": [],
            "store_overview_request": False,
            "answer_style": {"max_sentences": 2},
        }

    async def fake_select_knowledge_sources_with_llm(**kwargs):
        return [refund_source]

    async def fake_retrieve_company_info_sources(**kwargs):
        captured["contact_query_text"] = kwargs.get("query_text")
        captured["contact_must_tags"] = list(kwargs.get("must_tags") or [])
        return [contact_source]

    async def fake_attempt_grounded_knowledge_answer(**kwargs):
        captured["answer_source_ids"] = [
            str(source.source_id or "") for source in list(kwargs.get("knowledge_sources", []) or [])
        ]
        return "Contact us at sales@achadirect.com or +66 (0)2-629-5858 for the RMA.", ""

    monkeypatch.setattr(pipeline, "_retrieve_knowledge_sources", fake_retrieve_knowledge_sources)
    monkeypatch.setattr(pipeline, "_plan_knowledge_retrieval", fake_plan_knowledge_retrieval)
    monkeypatch.setattr(pipeline, "_select_knowledge_sources_with_llm", fake_select_knowledge_sources_with_llm)
    monkeypatch.setattr(pipeline, "_retrieve_company_info_sources", fake_retrieve_company_info_sources)
    monkeypatch.setattr(pipeline, "_attempt_grounded_knowledge_answer", fake_attempt_grounded_knowledge_answer)

    debug_meta: dict[str, object] = {}
    result = await pipeline._resolve_knowledge_payload(
        text="the product i order is wrong can i send it back or get a refund",
        locale="en-US",
        run_id="run-refund-contact-dependency",
        store_overview_request=False,
        normalized_text="the product i order is wrong can i send it back or get a refund",
        debug_meta=debug_meta,
        spans={"vector_search_ms": 0.0, "db_product_lookup_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert captured["contact_query_text"] == "customer support contact email phone showroom sales"
    assert captured["contact_must_tags"] == ["contact"]
    assert captured["answer_source_ids"] == ["refund-src", "contact-src"]
    assert [source.source_id for source in result["knowledge_sources"]] == ["refund-src", "contact-src"]
    assert result["knowledge_answer"].startswith("Contact us at sales@achadirect.com")
    assert debug_meta["knowledge_contact_dependency_required"] is True
    assert debug_meta["knowledge_contact_dependency_enriched"] is True
    assert debug_meta["knowledge_contact_dependency_satisfied"] is True
    assert debug_meta["knowledge_dependency_rules_required"] == ["contact_details"]
    assert debug_meta["knowledge_dependency_rules_enriched"] == ["contact_details"]
    assert debug_meta["knowledge_dependency_rules_satisfied"] == ["contact_details"]


@pytest.mark.asyncio
async def test_knowledge_payload_enriches_showroom_source_for_visit_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )
    visit_source = KnowledgeSource(
        source_id="visit-src",
        chunk_id="visit-chunk",
        title="Can I visit your showroom?",
        content_snippet="Please contact us before visiting our showroom.",
        category="Showroom",
        relevance=0.91,
        url="https://example.com/showroom-visit",
        distance=0.09,
    )
    showroom_source = KnowledgeSource(
        source_id="showroom-src",
        chunk_id="showroom-chunk",
        title="Bangkok Showroom Address and Hours",
        content_snippet="Our Bangkok showroom is open Monday to Saturday from 10 AM to 6 PM.",
        category="Store Overview",
        relevance=0.97,
        url="https://example.com/showroom-hours",
        distance=0.03,
    )
    captured: dict[str, object] = {}

    async def fake_retrieve_knowledge_sources(**kwargs):
        return [visit_source], ""

    async def fake_plan_knowledge_retrieval(**kwargs):
        return {
            "query_text": "can i visit your showroom and what are your opening hours",
            "topic": "showroom hours",
            "must_tags": [],
            "boost_tags": ["showroom"],
            "required_evidence": ["showroom hours"],
            "forbidden_topics": [],
            "store_overview_request": False,
            "answer_style": {"max_sentences": 2},
        }

    async def fake_select_knowledge_sources_with_llm(**kwargs):
        return [visit_source]

    async def fake_retrieve_company_info_sources(**kwargs):
        captured["showroom_query_text"] = kwargs.get("query_text")
        captured["showroom_must_tags"] = list(kwargs.get("must_tags") or [])
        return [showroom_source]

    async def fake_attempt_grounded_knowledge_answer(**kwargs):
        captured["answer_source_ids"] = [
            str(source.source_id or "") for source in list(kwargs.get("knowledge_sources", []) or [])
        ]
        return "Our Bangkok showroom is open Monday to Saturday, 10 AM to 6 PM.", ""

    monkeypatch.setattr(pipeline, "_retrieve_knowledge_sources", fake_retrieve_knowledge_sources)
    monkeypatch.setattr(pipeline, "_plan_knowledge_retrieval", fake_plan_knowledge_retrieval)
    monkeypatch.setattr(pipeline, "_select_knowledge_sources_with_llm", fake_select_knowledge_sources_with_llm)
    monkeypatch.setattr(pipeline, "_retrieve_company_info_sources", fake_retrieve_company_info_sources)
    monkeypatch.setattr(pipeline, "_attempt_grounded_knowledge_answer", fake_attempt_grounded_knowledge_answer)

    debug_meta: dict[str, object] = {}
    result = await pipeline._resolve_knowledge_payload(
        text="can i visit your showroom and what are your opening hours",
        locale="en-US",
        run_id="run-showroom-dependency",
        store_overview_request=False,
        normalized_text="can i visit your showroom and what are your opening hours",
        debug_meta=debug_meta,
        spans={"vector_search_ms": 0.0, "db_product_lookup_ms": 0.0, "llm_answer_ms": 0.0},
        external_call_counts={},
    )

    assert captured["showroom_query_text"] == "showroom address location opening hours visit phone email bangkok"
    assert captured["showroom_must_tags"] == ["store_overview"]
    assert captured["answer_source_ids"] == ["visit-src", "showroom-src"]
    assert [source.source_id for source in result["knowledge_sources"]] == ["visit-src", "showroom-src"]
    assert result["knowledge_answer"].startswith("Our Bangkok showroom is open")
    assert debug_meta["knowledge_showroom_dependency_required"] is True
    assert debug_meta["knowledge_showroom_dependency_enriched"] is True
    assert debug_meta["knowledge_showroom_dependency_satisfied"] is True
    assert debug_meta["knowledge_dependency_rules_required"] == ["showroom_details"]
    assert debug_meta["knowledge_dependency_rules_enriched"] == ["showroom_details"]
    assert debug_meta["knowledge_dependency_rules_satisfied"] == ["showroom_details"]


@pytest.mark.asyncio
async def test_generic_knowledge_selector_uses_llm_selected_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = ComponentPipeline(
        db=object(),
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )
    stock_source = KnowledgeSource(
        source_id="stock-src",
        chunk_id="stock-chunk",
        title="What if the item I ordered is out of stock?",
        content_snippet="If an ordered item is out of stock, the Sales Team will contact you about options.",
        category="Stock",
        relevance=0.74,
        url="https://example.com/stock",
        distance=0.26,
    )
    refund_source = KnowledgeSource(
        source_id="refund-src",
        chunk_id="refund-chunk",
        title="Do you have a Money Back Guarantee?",
        content_snippet="Contact us within 30 days for an RMA before returning products.",
        category="Refunds",
        relevance=0.92,
        url="https://example.com/refunds",
        distance=0.08,
    )

    async def fake_generate_chat_json(*args, **kwargs):
        assert kwargs.get("usage_kind") == "knowledge_evidence_select"
        return {
            "answerable": True,
            "selected_source_ids": ["stock-src"],
            "rejected": ["refund-src"],
            "missing_evidence": [],
            "reason": "The stock source directly answers the out-of-stock question.",
        }

    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)
    debug_meta: dict[str, object] = {}

    selected = await pipeline._select_knowledge_sources_with_llm(
        knowledge_query="what happens if my item is out of stock?",
        plan={
            "topic": "stock",
            "required_evidence": ["out-of-stock process"],
            "forbidden_topics": ["refunds"],
            "answer_style": {"max_sentences": 2},
        },
        candidates=[refund_source, stock_source],
        locale="en-US",
        debug_prefix="knowledge",
        usage_kind="knowledge_evidence_select",
        debug_meta=debug_meta,
        spans={"llm_answer_ms": 0.0},
        external_call_counts={},
        limit=3,
    )

    assert [source.source_id for source in selected] == ["stock-src"]
    assert debug_meta["knowledge_selector_source"] == "llm"
    assert debug_meta["knowledge_selector_answerable"] is True


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


def test_knowledge_answer_rewrites_internal_context_wording() -> None:
    answer = ComponentPipeline._rewrite_internal_knowledge_phrasing(
        "The available context does not list specific phone, email, or chat channels."
    )

    assert "available context" not in answer.lower()
    assert "verified phone number" in answer.lower()


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
