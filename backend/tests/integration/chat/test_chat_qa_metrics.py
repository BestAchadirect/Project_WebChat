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
        routing=ChatRouting(workflow="recommendation", execution_mode="component", needs_products=True),
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
            "workflow": "recommendation",
            "workflow_path": "component_primary",
            "reply_mode": "deterministic_recommendation",
            "recommendation_mode": "similar_items",
            "component_mode": "legacy",
            "retrieval_gate": {"use_products": True, "use_knowledge": False, "is_policy_like": False},
            "latency_spans": {"total_ms": 123.4},
            "external_call_count": 1,
            "llm_call_count": 0,
        },
    )

    metrics = qa_metrics.build_chat_qa_metrics(
        user_text="recommend titanium labrets",
        response=response,
        channel="widget",
    )

    assert metrics["workflow"] == "recommendation"
    assert metrics["response_workflow"] == "recommendation"
    assert metrics["status"] == "success"
    assert metrics["has_products"] is True
    assert metrics["product_count"] == 1
    assert metrics["follow_up_count"] == 1
    assert metrics["retrieval_source"] is None


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
