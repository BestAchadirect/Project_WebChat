from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatComponent, ChatResponse, ChatRouting, KnowledgeSource, ProductCard
from app.services.chat.runtime import persistence
from app.services.chat.observability import qa_metrics
from tests.fixtures.persistence import PersistenceDB


def _product() -> ProductCard:
    return ProductCard(
        id=uuid4(),
        object_id="OBJ-1",
        sku="SKU-1",
        legacy_sku=[],
        name="SKU-1",
        description=None,
        price=10.0,
        currency="USD",
        stock_status="in_stock",
        image_url=None,
        product_url=None,
        attributes={"material": "Titanium", "jewelry_type": "Labret"},
    )


def test_build_chat_qa_metrics_extracts_turn_observability() -> None:
    response = ChatResponse(
        conversation_id=1,
        reply_text="I found products that match what you're looking for.",
        carousel_msg="",
        product_carousel=[_product()],
        routing=ChatRouting(workflow="catalog", execution_mode="component", needs_products=True),
        sources=[
            KnowledgeSource(
                source_id="product_listings",
                title="Products",
                content_snippet="Products",
                relevance=0.9,
            )
        ],
        components=[
            ChatComponent(
                type="quick_replies",
                data={"items": ["See more titanium labrets"]},
            )
        ],
        debug={
            "workflow": "catalog",
            "workflow_path": "component_primary",
            "reply_mode": "deterministic_catalog",
            "component_mode": "legacy",
            "retrieval_gate": {"use_products": True, "use_knowledge": False, "is_policy_like": False},
            "latency_spans": {"total_ms": 123.4},
            "external_call_count": 1,
            "llm_call_count": 0,
            "conversation_state_enabled": True,
            "conversation_state_written": True,
            "conversation_state_filter_merge_applied": False,
            "conversation_state_loaded_version": 3,
            "grounding": {
                "status": "grounded",
                "safe_customer_action": "show_cards",
                "reasons": ["evidence_matches_plan"],
            },
        },
    )

    metrics = qa_metrics.build_chat_qa_metrics(
        conversation_id=1,
        user_text="show titanium labrets",
        response=response,
        channel="widget",
    )

    assert metrics["conversation_id"] == 1
    assert metrics["workflow"] == "catalog"
    assert metrics["response_workflow"] == "catalog"
    assert metrics["status"] == "success"
    assert metrics["has_products"] is True
    assert metrics["product_count"] == 1
    assert metrics["follow_up_count"] == 1
    assert metrics["retrieval_source"] is None
    assert metrics["conversation_state_enabled"] is True
    assert metrics["conversation_state_written"] is True
    assert metrics["conversation_state_loaded_version"] == 3
    assert metrics["grounding_status"] == "grounded"
    assert metrics["grounding_safe_action"] == "show_cards"
    assert metrics["grounding_reason_count"] == 1
    assert metrics["failure_bucket"] == "other"
    assert metrics["failure_analysis"]["bucket"] == "other"
    assert metrics["failure_analysis"]["severity"] == "low"


def test_build_chat_qa_metrics_extracts_harness_trace_observability() -> None:
    response = ChatResponse(
        conversation_id=2,
        reply_text="RING-1 is in stock.",
        carousel_msg="",
        product_carousel=[],
        routing=ChatRouting(workflow="catalog", execution_mode="agentic", needs_products=True),
        sources=[],
        debug={
            "workflow": "catalog",
            "workflow_path": "agentic_primary",
            "agentic": {"selected": True, "used_tools": False},
            "harness_trace": {
                "run_id": "chat-trace-test",
                "route": "catalog",
                "workflow": "product_detail",
                "execution_mode": "agentic",
                "tools_called": ["check_inventory_db"],
                "retrieved_products": 1,
                "retrieved_sources": 0,
                "grounding_status": "grounded",
                "fallback_used": False,
                "clarification_required": False,
            },
        },
    )

    metrics = qa_metrics.build_chat_qa_metrics(
        conversation_id=2,
        user_text="stock for RING-1",
        response=response,
        channel="widget",
    )

    assert metrics["harness_trace_present"] is True
    assert metrics["harness_run_id"] == "chat-trace-test"
    assert metrics["harness_route"] == "catalog"
    assert metrics["harness_workflow"] == "product_detail"
    assert metrics["harness_execution_mode"] == "agentic"
    assert metrics["harness_fallback_reason"] is None
    assert metrics["harness_clarification_reason"] is None
    assert metrics["harness_tool_count"] == 1
    assert metrics["harness_tools_called"] == ["check_inventory_db"]
    assert metrics["harness_retrieved_products"] == 1
    assert metrics["grounding_status"] == "grounded"
    assert metrics["action_completed"] is True
    assert metrics["action_kind"] == "agentic_tools"
    assert metrics["tool_first_selected"] is True
    assert metrics["agentic_fallback_to_component"] is False
    assert metrics["agentic_grounding_failed"] is False


def test_summarize_chat_metrics_includes_conversation_state_diagnostics() -> None:
    rows = [
        {
            "status": "success",
            "workflow": "catalog",
            "action_kind": "agentic_tools",
            "action_completed": True,
            "conversation_state_enabled": True,
            "conversation_state_written": True,
            "conversation_state_filter_merge_applied": True,
            "conversation_state_loaded_version": 3,
            "grounding_status": "grounded",
            "grounding_safe_action": "show_cards",
            "failure_bucket": "other",
            "harness_route": "catalog",
            "harness_workflow": "product_detail",
            "harness_execution_mode": "agentic",
            "harness_grounding_status": "grounded",
            "harness_fallback_used": False,
            "harness_fallback_reason": "",
            "harness_clarification_required": False,
            "harness_clarification_reason": "",
            "harness_tool_count": 2,
            "harness_tools_called": ["search_products", "check_inventory_db"],
            "harness_retrieved_products": 3,
            "harness_retrieved_sources": 0,
            "tool_first_selected": True,
            "agentic_fallback_to_component": False,
            "agentic_grounding_failed": False,
            "agentic_fallback_reason": "",
            "tone_repeat_hit": 1,
            "tone_filler_stripped": 0,
        },
        {
            "status": "fallback",
            "workflow": "fallback",
            "action_kind": "",
            "action_completed": False,
            "conversation_state_enabled": True,
            "conversation_state_written": False,
            "conversation_state_filter_merge_applied": False,
            "conversation_state_loaded_version": 3,
            "grounding_status": "weak",
            "grounding_safe_action": "clarify",
            "failure_analysis": {"bucket": "hard_constraint_no_match"},
            "harness_route": "fallback",
            "harness_workflow": "catalog_search",
            "harness_execution_mode": "fallback",
            "harness_grounding_status": "weak",
            "harness_fallback_used": True,
            "harness_fallback_reason": "agentic_empty",
            "harness_clarification_required": True,
            "harness_clarification_reason": "missing_product_anchor",
            "harness_tool_count": 0,
            "harness_tools_called": [],
            "harness_retrieved_products": 0,
            "harness_retrieved_sources": 1,
            "tool_first_selected": True,
            "agentic_fallback_to_component": True,
            "agentic_grounding_failed": True,
            "agentic_fallback_reason": "agentic_grounding_failed",
            "tone_repeat_hit": 0,
            "tone_filler_stripped": 2,
        },
    ]

    summary = qa_metrics.summarize_chat_metrics(rows)

    assert summary["total_rows"] == 2
    assert summary["conversation_state_enabled"] == 2
    assert summary["conversation_state_written"] == 1
    assert summary["conversation_state_filter_merge_applied"] == 1
    assert summary["conversation_state_loaded_versions"] == {"3": 2}
    assert summary["by_grounding_status"] == {"grounded": 1, "weak": 1}
    assert summary["by_grounding_safe_action"] == {"clarify": 1, "show_cards": 1}
    assert summary["by_failure_bucket"] == {"hard_constraint_no_match": 1, "other": 1}
    assert summary["by_harness_route"] == {"catalog": 1, "fallback": 1}
    assert summary["by_harness_workflow"] == {"catalog_search": 1, "product_detail": 1}
    assert summary["by_harness_execution_mode"] == {"agentic": 1, "fallback": 1}
    assert summary["by_harness_grounding_status"] == {"grounded": 1, "weak": 1}
    assert summary["by_harness_fallback_reason"] == {"agentic_empty": 1}
    assert summary["by_harness_clarification_reason"] == {"missing_product_anchor": 1}
    assert summary["by_harness_tool"] == {"check_inventory_db": 1, "search_products": 1}
    assert summary["by_agentic_fallback_reason"] == {"agentic_grounding_failed": 1}
    assert summary["top_harness_tools"] == [
        {"tool": "check_inventory_db", "count": 1},
        {"tool": "search_products", "count": 1},
    ]
    assert summary["tool_first_selected"] == 2
    assert summary["agentic_fallback_to_component"] == 1
    assert summary["agentic_grounding_failed"] == 1
    assert summary["harness_fallback_used"] == 1
    assert summary["harness_clarification_required"] == 1
    assert summary["harness_tool_calls"] == 2
    assert summary["harness_retrieved_products"] == 3
    assert summary["harness_retrieved_sources"] == 1
    assert summary["tone_repeat_hit"] == 1
    assert summary["tone_filler_stripped"] == 2


def test_summarize_chat_metrics_counts_expected_tool_misses() -> None:
    rows = [
        {
            "status": "fallback",
            "workflow": "knowledge",
            "agentic_selected": True,
            "tool_first_selected": True,
            "agentic_fallback_to_component": True,
            "agentic_fallback_reason": "agentic_expected_tool_missing",
            "agentic_expected_tool_missing": True,
            "agentic_missing_expected_tools": ["search_knowledge_base"],
        },
        {
            "status": "success",
            "workflow": "catalog",
            "agentic_selected": True,
            "tool_first_selected": True,
            "agentic_fallback_to_component": False,
            "agentic_expected_tool_missing": False,
            "agentic_missing_expected_tools": [],
        },
    ]

    summary = qa_metrics.summarize_chat_metrics(rows)

    assert summary["tool_first_selected"] == 2
    assert summary["agentic_fallback_to_component"] == 1
    assert summary["agentic_expected_tool_missing"] == 1
    assert summary["by_agentic_fallback_reason"] == {"agentic_expected_tool_missing": 1}
    assert summary["by_agentic_missing_expected_tool"] == {"search_knowledge_base": 1}


def test_build_tool_first_rollout_summary_exposes_dashboard_counters() -> None:
    rows = [
        {
            "status": "success",
            "workflow": "catalog",
            "tool_first_selected": True,
            "agentic_fallback_to_component": False,
            "agentic_expected_tool_missing": False,
            "agentic_grounding_failed": False,
            "harness_route": "catalog",
            "harness_workflow": "catalog_search",
            "harness_tools_called": ["search_products"],
            "harness_tool_count": 1,
            "failure_bucket": "other",
        },
        {
            "status": "fallback",
            "workflow": "knowledge",
            "tool_first_selected": True,
            "agentic_fallback_to_component": True,
            "agentic_expected_tool_missing": True,
            "agentic_grounding_failed": False,
            "agentic_fallback_reason": "agentic_expected_tool_missing",
            "agentic_missing_expected_tools": ["search_knowledge_base"],
            "harness_route": "knowledge",
            "harness_workflow": "policy_info",
            "harness_tools_called": [],
            "failure_bucket": "agentic_expected_tool_missing",
        },
        {
            "status": "fallback",
            "workflow": "catalog",
            "tool_first_selected": True,
            "agentic_fallback_to_component": True,
            "agentic_expected_tool_missing": False,
            "agentic_grounding_failed": True,
            "agentic_fallback_reason": "agentic_grounding_failed",
            "harness_route": "catalog",
            "harness_workflow": "catalog_search",
            "harness_tools_called": ["search_products"],
            "harness_tool_count": 1,
            "failure_bucket": "agentic_grounding_failed",
        },
    ]

    summary = qa_metrics.build_tool_first_rollout_summary(rows)

    assert summary["total_rows"] == 3
    assert summary["tool_first_selected"] == 3
    assert summary["fallback_to_component"] == 2
    assert summary["expected_tool_missing"] == 1
    assert summary["grounding_failed"] == 1
    assert summary["top_tools"] == [{"tool": "search_products", "count": 2}]
    assert summary["by_agentic_fallback_reason"] == {
        "agentic_expected_tool_missing": 1,
        "agentic_grounding_failed": 1,
    }
    assert summary["by_agentic_missing_expected_tool"] == {"search_knowledge_base": 1}


@pytest.mark.asyncio
async def test_finalize_response_persists_chat_metrics_in_token_usage() -> None:
    db = PersistenceDB(assert_on_rollback=True)
    response = ChatResponse(
        conversation_id=1,
        reply_text="Fallback answer",
        carousel_msg="",
        product_carousel=[],
        routing=ChatRouting(workflow="fallback", execution_mode="component", needs_clarification=True),
        sources=[],
        debug={"workflow": "knowledge", "workflow_path": "fallback_component"},
    )

    await persistence.finalize_response(
        db=db,
        conversation_id=1,
        user_text="what is your warranty policy",
        response=response,
        token_usage={"prompt_tokens": 10},
        channel="widget",
    )

    assert db.committed is True
    qa_log = next(obj for obj in db.added if getattr(obj, "__tablename__", "") == "qa_logs")
    assistant_msg = db.added[1]
    assert qa_log.token_usage["chat_metrics"]["status"] == "fallback"
    assert qa_log.token_usage["chat_metrics"]["conversation_id"] == 1
    assert qa_log.token_usage["chat_metrics"]["workflow"] == "knowledge"
    assert qa_log.token_usage["chat_metrics"]["route"] == "fallback_component"
    assert qa_log.token_usage["chat_metrics"]["failure_bucket"] == "other"
