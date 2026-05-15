from __future__ import annotations

import json

import pytest

from app.services.ai.llm_service import llm_service
from app.services.chat.agentic.orchestrator import AgentOrchestrator
from app.services.chat.agentic.tool_registry import GetProductDetailsArgs, SearchProductsArgs
from tests.evaluation.chat.scenario_loader import load_scenarios
from tests.fixtures.db_grounding import (
    fetch_seeded_product,
    grounded_db_engine,  # noqa: F401
    grounded_db_session,  # noqa: F401
    grounded_query_embedding,
    grounded_seed,  # noqa: F401
)


pytestmark = [pytest.mark.evaluation, pytest.mark.db_grounded]

CASES = load_scenarios("db_grounded_scenarios.yaml")


async def _fake_embedding(query: str) -> list[float]:
    return grounded_query_embedding(query)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_db_grounded_catalog_answers(
    case: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    grounded_db_session,
    grounded_seed,
) -> None:
    expected = dict(case["expected"] or {})
    scenario_id = str(case["id"])

    if scenario_id == "db_product_code_detail":
        if "DMBJ38" not in grounded_seed.products:
            pytest.xfail("grounded seed does not currently include DMBJ38")

        expected_product = await fetch_seeded_product(grounded_db_session, "DMBJ38")
        orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="db-eval-detail", channel="widget")
        payload = await orchestrator.registry.get_product_details(GetProductDetailsArgs(sku="DMBJ38"))
        normalized = orchestrator.registry.normalize_tool_result(tool_name="get_product_details", result=payload)

        assert payload["source"] == "catalog_db"
        assert payload["status"] == "ok"
        assert normalized.result_count == 1
        assert normalized.products[0].sku == expected_product.sku
        assert normalized.products[0].attributes["master_code"] == expected["product_anchor"]
        return

    if scenario_id == "db_gold_labret_search":
        monkeypatch.setattr(llm_service, "generate_embedding", _fake_embedding)
        orchestrator = AgentOrchestrator(db=grounded_db_session, run_id="db-eval-search", channel="widget")
        execution_filters = {"material": "gold pvd", "jewelry_type": "labret"}
        expected_filters = dict(expected.get("filters") or {})
        payload = await orchestrator.registry.search_products(
            SearchProductsArgs.model_validate(
                {
                    "query": "show me gold labret",
                    "filters": execution_filters,
                    "page": 1,
                    "pageSize": 5,
                }
            )
        )
        normalized = orchestrator.registry.normalize_tool_result(tool_name="search_products", result=payload)

        assert payload["source"] == "catalog_db"
        assert payload["status"] == "ok"
        assert normalized.result_count >= 1
        assert all(
            str(card.attributes.get("jewelry_type") or "").strip().lower() == expected_filters["product_type"]
            for card in normalized.products
        )
        assert all(
            str(expected_filters["material"]).strip().lower() in str(card.attributes.get("material") or "").strip().lower()
            for card in normalized.products
        )

        calls = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_gold",
                        "name": "search_products",
                        "arguments": {
                            "query": "show me gold labret",
                            "filters": execution_filters,
                            "page": 1,
                            "pageSize": 5,
                        },
                        "raw_arguments": json.dumps(
                            {
                                "query": "show me gold labret",
                                "filters": execution_filters,
                                "page": 1,
                                "pageSize": 5,
                            }
                        ),
                    }
                ],
            },
            {
                "content": "I found gold labret products from the catalog.",
                "tool_calls": [],
            },
        ]

        async def fake_chat_with_tools(**kwargs):
            del kwargs
            return calls.pop(0)

        monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_chat_with_tools)
        result = await orchestrator.run(user_text="show me gold labret")

        assert result.used_tools is True
        assert result.product_carousel
        assert all(
            str(card.attributes.get("jewelry_type") or "").strip().lower() == expected_filters["product_type"]
            for card in result.product_carousel
        )
        assert all(
            str(expected_filters["material"]).strip().lower() in str(card.attributes.get("material") or "").strip().lower()
            for card in result.product_carousel
        )
        return

    raise AssertionError(f"Unhandled db-grounded scenario: {scenario_id}")
