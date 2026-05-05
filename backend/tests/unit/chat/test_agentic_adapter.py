from __future__ import annotations

import uuid

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatRouting, KnowledgeSource, ProductCard
from app.services.chat.agentic.orchestrator import AgentRunResult
from app.services.chat.runtime.agentic_adapter import build_agentic_response
from app.services.chat.runtime.execution_coordinator import finalize_agentic_response


def test_build_agentic_response_normalizes_result_and_preserves_component_contract() -> None:
    result = AgentRunResult(
        final_reply="Here are two matching products.",
        used_tools=True,
        product_carousel=[
            ProductCard(
                id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                sku="DG-1",
                legacy_sku=[],
                name="Gold Ring",
                price=19.99,
                currency="USD",
                stock_status="in_stock",
                attributes={"material": "Gold"},
            )
        ],
        sources=[
            KnowledgeSource(
                source_id="kb-ship",
                title="Shipping Policy",
                content_snippet="Orders usually ship quickly.",
                category="Policy",
                relevance=0.95,
            )
        ],
        follow_up_questions=["Show similar pieces"],
        trace=[{"tool": "search_products", "status": "ok"}],
    )

    response = build_agentic_response(
        conversation_id=42,
        routing=ChatRouting(
            workflow="catalog",
            execution_mode="agentic",
            needs_products=True,
            reason="fixture",
            selection_source="fixture",
        ),
        query_summary="gold ring",
        agentic_result=result,
    )

    assert response.reply_text == "Here are two matching products."
    assert response.meta is not None
    assert response.meta.source == "tool"
    assert response.meta.product_result_count == 1
    assert response.sources[0].source_id == "kb-ship"
    assert [component.type.value for component in response.components] == [
        "assistant_message",
        "product_cards",
        "quick_replies",
    ]


@pytest.mark.asyncio
async def test_finalize_agentic_response_rejects_non_success_outcome() -> None:
    with pytest.raises(ValueError, match="requires tool_success outcome"):
        await finalize_agentic_response(
            object(),
            conversation_id=99,
            routing=ChatRouting(
                workflow="knowledge",
                execution_mode="agentic",
                needs_knowledge=True,
                reason="fixture",
                selection_source="fixture",
            ),
            query_summary="shipping policy",
            agentic_result=AgentRunResult.no_tool_answer(
                final_reply="I think the shipping policy is standard.",
                trace=[],
            ),
            user_text="shipping policy",
            channel="widget",
            run_id="run-test",
            debug_meta={},
            spans={},
            total_started=0.0,
        )
