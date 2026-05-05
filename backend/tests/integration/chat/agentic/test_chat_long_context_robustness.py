from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.services.ai.llm_service import llm_service
from app.services.chat.agentic.orchestrator import AgentOrchestrator
from app.services.chat.agentic.tool_registry import AgentToolRegistry
from app.services.chat.observability import accuracy_eval
from tests.fixtures.chat import load_json_dataset


DATASET_PATH = Path(__file__).resolve().parents[3] / "regression" / "data" / "chat_long_context_cases.json"
CASES = load_json_dataset(DATASET_PATH, infer_suite=True)

pytestmark = [pytest.mark.agentic, pytest.mark.long_context]


def _history_from_case(case: dict[str, object]) -> list[dict[str, str]]:
    turns = list(case.get("turns") or [])
    if len(turns) <= 1:
        return []
    return [dict(turn) for turn in turns[:-1] if isinstance(turn, dict)]


def _user_text_from_case(case: dict[str, object]) -> str:
    inputs = dict(case.get("inputs") or {})
    return str(inputs.get("message") or "").strip()


def _agentic_response_payload(result, *, case: dict[str, object]) -> dict[str, object]:
    products = [card.model_dump(mode="json") for card in list(result.product_carousel or [])]
    sources = [source.model_dump(mode="json") for source in list(result.sources or [])]
    fallback_debug = dict(dict(case.get("fallback_actual_response") or {}).get("debug") or {})
    if products and sources:
        workflow = "catalog"
    elif sources:
        workflow = "knowledge"
    elif products:
        workflow = "catalog"
    else:
        workflow = "fallback"
    return {
        "routing": {"workflow": workflow},
        "reply_text": str(result.final_reply or ""),
        "follow_up_questions": list(result.follow_up_questions or []),
        "sources": sources,
        "product_carousel": products,
        "components": [],
        "debug": fallback_debug,
    }


def pytest_generate_tests(metafunc):
    if "case" not in metafunc.fixturenames:
        return
    metafunc.parametrize("case", CASES, ids=lambda case: case["id"])


@pytest.mark.asyncio
async def test_long_context_cases_replay_history_and_preserve_anchor(
    monkeypatch: pytest.MonkeyPatch,
    case: dict[str, object],
) -> None:
    if case["id"] == "long_context_product_reanchor_gold_variant":
        tool_rounds = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_gold",
                        "name": "get_product_details",
                        "arguments": {"sku": "EVAL-GOLD-LAB-1"},
                        "raw_arguments": "{\"sku\":\"EVAL-GOLD-LAB-1\"}",
                        "argument_error": None,
                    }
                ],
                "finish_reason": "tool_calls",
            },
            {
                "content": "The gold labret variant EVAL-GOLD-LAB-1 is out of stock.",
                "tool_calls": [],
                "finish_reason": "stop",
            },
        ]
    elif case["id"] == "long_context_policy_follow_up_after_product_shift":
        tool_rounds = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_returns",
                        "name": "search_knowledge_base",
                        "arguments": {"query": "returns policy", "category": "Policy", "limit": 1},
                        "raw_arguments": "{\"query\":\"returns policy\",\"category\":\"Policy\",\"limit\":1}",
                        "argument_error": None,
                    }
                ],
                "finish_reason": "tool_calls",
            },
            {
                "content": "Eligible jewelry can be returned within 30 days.",
                "tool_calls": [],
                "finish_reason": "stop",
            },
        ]
    else:
        tool_rounds = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_product",
                        "name": "search_products",
                        "arguments": {
                            "query": "titanium labrets",
                            "filters": {"material": "titanium", "jewelry_type": "labret"},
                            "page": 1,
                            "pageSize": 1,
                        },
                        "raw_arguments": "{\"query\":\"titanium labrets\",\"filters\":{\"material\":\"titanium\",\"jewelry_type\":\"labret\"},\"page\":1,\"pageSize\":1}",
                        "argument_error": None,
                    },
                    {
                        "id": "call_policy",
                        "name": "search_knowledge_base",
                        "arguments": {"query": "returns policy", "category": "Policy", "limit": 1},
                        "raw_arguments": "{\"query\":\"returns policy\",\"category\":\"Policy\",\"limit\":1}",
                        "argument_error": None,
                    },
                ],
                "finish_reason": "tool_calls",
            },
            {
                "content": "Here are titanium labrets, and unopened jewelry can be returned within 30 days.",
                "tool_calls": [],
                "finish_reason": "stop",
            },
        ]

    captured_messages: list[list[dict[str, object]]] = []

    async def fake_generate_chat_with_tools(**kwargs):
        captured_messages.append(list(kwargs.get("messages") or []))
        return tool_rounds.pop(0)

    async def fake_execute_tool(self, tool_name, raw_arguments):
        if tool_name == "get_product_details":
            sku = str(raw_arguments.get("sku") or "")
            if sku == "EVAL-GOLD-LAB-1":
                return {
                    "tool": "get_product_details",
                    "status": "ok",
                    "source": "catalog_db",
                    "found": True,
                    "ambiguous": False,
                    "sku": sku,
                    "matched_by": "direct_reference",
                    "product": {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "sku": sku,
                        "name": "Gold Labret",
                        "price": 24.0,
                        "currency": "USD",
                        "stock_status": "out_of_stock",
                        "attributes": {
                            "material": "gold",
                            "jewelry_type": "labret",
                        },
                    },
                    "candidates": [],
                }
            return {
                "tool": "get_product_details",
                "status": "not_found",
                "source": "catalog_db",
                "found": False,
                "ambiguous": False,
                "sku": sku,
                "matched_by": "",
                "candidates": [],
            }
        if tool_name == "search_knowledge_base":
            return {
                "tool": "search_knowledge_base",
                "status": "ok",
                "source": "knowledge_db",
                "items": [
                    {
                        "source_id": "eval_returns_policy",
                        "title": "Eval Returns Policy",
                        "content_snippet": "Eligible jewelry can be returned within 30 days.",
                        "category": "Policy",
                        "relevance": 0.93,
                    }
                ],
                "totalItems": 1,
                "query": str(raw_arguments.get("query") or ""),
                "category": str(raw_arguments.get("category") or "Policy"),
                "limit": 1,
            }
        if tool_name == "search_products":
            return {
                "tool": "search_products",
                "status": "ok",
                "source": "catalog_db",
                "items": [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "sku": "EVAL-TI-LAB-1",
                        "name": "Titanium Labret",
                        "price": 19.5,
                        "currency": "USD",
                        "stock_status": "in_stock",
                        "attributes": {
                            "material": "titanium",
                            "jewelry_type": "labret",
                        },
                    }
                ],
                "totalItems": 1,
                "query": str(raw_arguments.get("query") or ""),
                "filters": {},
                "page": 1,
                "pageSize": 1,
                "totalPages": 1,
            }
        raise AssertionError(f"unexpected tool call: {tool_name}")

    monkeypatch.setattr(llm_service, "generate_chat_with_tools", fake_generate_chat_with_tools)
    monkeypatch.setattr(AgentToolRegistry, "execute_tool", fake_execute_tool)

    orchestrator = AgentOrchestrator(db=None, run_id=f"long-context-{case['id']}", channel="widget")
    result = await orchestrator.run(
        user_text=_user_text_from_case(case),
        history=_history_from_case(case),
        reply_language="en-US",
    )

    assert len(captured_messages) >= 1
    first_round_messages = captured_messages[0]
    expected_history = _history_from_case(case)
    assert len(first_round_messages) == len(expected_history) + 2
    for expected, actual in zip(expected_history, first_round_messages[1:-1], strict=True):
        assert actual["role"] == expected["role"]
        assert actual["content"] == expected["content"]

    actual_results = {case["id"]: _agentic_response_payload(result, case=case)}
    evaluated = accuracy_eval.evaluate_case(case, actual_results=actual_results)
    assert evaluated["passed"], evaluated["mismatches"]
