from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")
pytestmark = pytest.mark.agentic

from app.services.chat.agentic.orchestrator import AgentOrchestrator


def test_result_count_counts_candidates_for_ambiguous_lookup() -> None:
    count = AgentOrchestrator._result_count(
        {
            "tool": "get_product_details",
            "status": "ambiguous",
            "candidates": [{}, {}, {}],
        }
    )

    assert count == 3


def test_collect_products_keeps_ambiguous_candidates_renderable() -> None:
    orchestrator = AgentOrchestrator(db=object(), run_id="run-1", channel="widget")
    products: dict[str, object] = {}

    orchestrator._collect_products(
        "get_product_details",
        {
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
        products,
    )

    assert len(products) == 2

