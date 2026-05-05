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
        user_text="show titanium labrets",
        response=response,
        channel="widget",
    )

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
    assert summary["tone_repeat_hit"] == 1
    assert summary["tone_filler_stripped"] == 2


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
    assert qa_log.token_usage["chat_metrics"]["workflow"] == "knowledge"
    assert qa_log.token_usage["chat_metrics"]["route"] == "fallback_component"
