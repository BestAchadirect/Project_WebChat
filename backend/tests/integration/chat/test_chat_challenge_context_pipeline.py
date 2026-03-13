from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.services.chat import routing_policy
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.components.types import ComponentSource
from tests.fixtures.chat import KnowledgeStub, RedisStub


@pytest.fixture(autouse=True)
def chat_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_SHADOW_MODE", False)
    monkeypatch.setattr(settings, "CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS", False)
    monkeypatch.setattr(settings, "CHAT_CONVERSATION_STATE_ENABLED", False)
    monkeypatch.setattr(settings, "CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST", 0)
    monkeypatch.setattr(settings, "CHAT_TONE_HUMANIZER_ENABLED", False)


def _workflow_decision() -> routing_policy.WorkflowDecision:
    return routing_policy.WorkflowDecision(
        workflow="catalog",
        source=ComponentSource.SQL,
        needs_products=True,
        needs_knowledge=False,
        needs_clarification=False,
        store_overview_request=False,
        reason="challenge_override",
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_component_pipeline_inventory_reverify_returns_verified_stock_message() -> None:
    class CatalogStub:
        async def get_inventory_snapshot(self, sku: str):
            assert sku == "ABC-1"
            return {
                "found": True,
                "sku": "ABC-1",
                "stock_status": "in_stock",
                "last_stock_sync_at": "2026-03-12T00:00:00Z",
                "source": "db",
            }

    pipeline = ComponentPipeline(
        db=SimpleNamespace(),
        catalog_search=CatalogStub(),
        knowledge_retrieval=KnowledgeStub(),
        redis_cache=RedisStub(),
    )

    result = await pipeline.run(
        request=ChatRequest(
            user_id="guest-1",
            message="You are wrong, ABC-1 is out of stock.",
            locale="en-US",
        ),
        conversation_id=77,
        run_id="run-challenge-inventory",
        route_decision_override=_workflow_decision(),
        challenge_context={
            "mode": "inventory_reverify",
            "target_sku": "ABC-1",
            "reason": "stock_dispute_detected",
        },
    )

    assert result.response.routing.workflow == "catalog"
    assert "currently in stock" in str(result.response.reply_text or "").lower()
    assert result.debug.get("inventory_verified_sku") == "ABC-1"
    assert result.debug.get("inventory_verified_status") == "in_stock"
    assert result.external_call_counts.get("inventory_verify") == 1

