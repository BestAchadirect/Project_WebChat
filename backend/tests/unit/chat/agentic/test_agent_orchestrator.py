from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")
pytestmark = pytest.mark.agentic

from app.schemas.chat import ProductCard
from app.services.chat.agentic.orchestrator import AgentOrchestrator
from app.services.chat.agentic.tool_registry import AgentToolRegistry


def test_result_count_counts_candidates_for_ambiguous_lookup() -> None:
    count = AgentToolRegistry._result_count(
        {
            "tool": "get_product_details",
            "status": "ambiguous",
            "candidates": [{}, {}, {}],
        }
    )

    assert count == 3


def test_merge_tool_artifacts_keeps_ambiguous_candidates_renderable() -> None:
    orchestrator = AgentOrchestrator(db=object(), run_id="run-1", channel="widget")
    products: dict[str, ProductCard] = {}
    sources = {}

    normalized = orchestrator.registry.normalize_tool_result(
        tool_name="get_product_details",
        result={
            "tool": "get_product_details",
            "status": "ambiguous",
            "candidates": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "sku": "LAB-14",
                    "legacy_sku": [],
                    "name": "LAB-14",
                    "price": 10.0,
                    "currency": "USD",
                    "stock_status": "in_stock",
                    "attributes": {"material": "Titanium"},
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "sku": "LAB-14-ALT",
                    "legacy_sku": [],
                    "name": "LAB-14 Alt",
                    "price": 12.0,
                    "currency": "USD",
                    "stock_status": "out_of_stock",
                    "attributes": {"material": "Steel"},
                },
            ],
        },
    )
    orchestrator._merge_tool_artifacts(
        normalized=normalized,
        products=products,
        sources=sources,
    )

    assert len(products) == 2
    assert all(isinstance(card, ProductCard) for card in products.values())
