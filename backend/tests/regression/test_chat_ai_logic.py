from dataclasses import dataclass
from types import SimpleNamespace
import asyncio
from contextlib import ExitStack
from unittest.mock import patch

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.services.ai.llm_service import llm_service
from app.services.chat.agentic.orchestrator import AgentRunResult
from app.services.chat.observability import accuracy_eval
from app.services.chat.parsing.parser_rule_types import ParserRuleSet, build_rule_set
from app.services.chat.routing.contracts import UnderstandingResult
from app.services.chat.service import ChatService
from tests.fixtures.chat import (
    DummyConversation,
    build_component_pipeline_result,
    build_knowledge_sources,
    build_product_cards,
)


@dataclass(frozen=True)
class ChatParserFixture:
    parser_rules: ParserRuleSet
    alias_map: dict[str, dict[str, str]]


_CASES_CACHE = None
_ACTUAL_RESULTS_CACHE = None


def _get_cases():
    global _CASES_CACHE
    if _CASES_CACHE is None:
        _CASES_CACHE = accuracy_eval.load_accuracy_cases()
    return _CASES_CACHE


def _get_actual_results():
    global _ACTUAL_RESULTS_CACHE
    if _ACTUAL_RESULTS_CACHE is None:
        response_cases = [
            case
            for case in _get_cases()
            if str(case.get("kind") or "").strip().lower() in {"response_contract", "context_contract"}
        ]
        _ACTUAL_RESULTS_CACHE = _build_response_contract_actual_results(response_cases)
    return _ACTUAL_RESULTS_CACHE


def _build_understanding_result(*, case: dict[str, object]) -> UnderstandingResult:
    inputs = dict(case.get("inputs") or {})
    fixture = dict(case.get("runtime_fixture") or {})
    understanding = dict(fixture.get("understanding") or {})
    return UnderstandingResult(
        normalized_text=str(inputs.get("message") or "").strip().lower(),
        locale=str(inputs.get("locale") or "en-US"),
        channel="widget",
        sku_tokens=list(understanding.get("sku_tokens") or []),
        workflow_hypothesis=str(understanding.get("workflow_hypothesis") or "clarify"),
        intent_confidence=float(understanding.get("intent_confidence", 0.9) or 0.9),
        reason=str(understanding.get("reason") or "fixture"),
        knowledge_query=str(understanding.get("knowledge_query") or ""),
        store_overview_request=bool(understanding.get("store_overview_request", False)),
        needs_products=bool(understanding.get("needs_products", False)),
        needs_knowledge=bool(understanding.get("needs_knowledge", False)),
        failure_reason=str(understanding.get("failure_reason") or ""),
        entity_hints=dict(understanding.get("entity_hints") or {}),
        debug={"understanding_source": "fixture"},
    )


def _build_component_kwargs(*, case: dict[str, object]) -> dict[str, object]:
    fixture = dict(case.get("runtime_fixture") or {})
    component_response = dict(fixture.get("component_response") or {})
    return {
        "reply_text": str(component_response.get("reply_text") or ""),
        "response_workflow": str(component_response.get("workflow") or "fallback"),
        "source": str(component_response.get("source") or "error"),
        "response_debug": dict(component_response.get("debug") or {}),
        "components": list(component_response.get("components") or []),
        "sources": list(component_response.get("sources") or []),
        "product_carousel": list(component_response.get("product_carousel") or []),
    }


def _build_agentic_result(*, case: dict[str, object]) -> AgentRunResult:
    fixture = dict(case.get("runtime_fixture") or {})
    agentic = dict(fixture.get("agentic_result") or {})
    outcome = str(fixture.get("mode") or "").strip().lower()
    if outcome == "agentic_success":
        return AgentRunResult.tool_success(
            final_reply=str(agentic.get("final_reply") or ""),
            product_carousel=build_product_cards(list(agentic.get("product_carousel") or [])),
            sources=build_knowledge_sources(list(agentic.get("sources") or [])),
            follow_up_questions=list(agentic.get("follow_up_questions") or []),
            carousel_msg=str(agentic.get("carousel_msg") or ""),
            trace=list(agentic.get("trace") or []),
        )
    return AgentRunResult.no_tool_answer(
        final_reply=str(agentic.get("final_reply") or "fixture no-tool answer"),
        trace=list(agentic.get("trace") or []),
    )


def _build_response_contract_actual_results(cases: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    actual_results: dict[str, dict[str, object]] = {}
    for case in list(cases or []):
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            continue
        fixture = dict(case.get("runtime_fixture") or {})
        if not fixture:
            continue

        understanding_result = _build_understanding_result(case=case)
        component_kwargs = _build_component_kwargs(case=case)
        mode = str(fixture.get("mode") or "component").strip().lower()
        conversation = DummyConversation()

        async def fake_understanding(**kwargs):
            del kwargs
            return understanding_result

        async def fake_get_or_create_user(self, user_id: str, name: str | None = None, email: str | None = None):
            del self, name, email
            return SimpleNamespace(id=user_id, customer_name=None, email=None)

        async def fake_get_or_create_conversation(self, user, conversation_id):
            del self, user, conversation_id
            return conversation

        async def fake_finalize_response(self, *, response, **kwargs):
            del self, kwargs
            return response

        async def fake_get_history(self, conversation_id: int, limit: int = 8):
            del self, conversation_id, limit
            return []

        async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
            del self, run_id, kwargs
            return build_component_pipeline_result(
                request=request,
                conversation_id=conversation_id,
                **component_kwargs,
            )

        async def fake_agentic_workflow(
            self,
            *,
            user_text: str,
            conversation_id: int,
            run_id: str,
            channel: str,
            reply_language: str,
        ):
            del self, user_text, conversation_id, run_id, channel, reply_language
            if mode == "agentic_error":
                raise RuntimeError(str(fixture.get("agentic_error") or "agentic regression failure"))
            return _build_agentic_result(case=case)

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.chat.runtime.unified_chat_runtime.build_understanding_result",
                    fake_understanding,
                )
            )
            stack.enter_context(patch.object(ChatService, "get_or_create_user", fake_get_or_create_user))
            stack.enter_context(
                patch.object(ChatService, "get_or_create_conversation", fake_get_or_create_conversation)
            )
            stack.enter_context(patch.object(ChatService, "_finalize_response", fake_finalize_response))
            stack.enter_context(patch.object(ChatService, "get_history", fake_get_history))
            stack.enter_context(patch.object(ChatService, "_run_component_pipeline", fake_component_pipeline))
            stack.enter_context(patch.object(ChatService, "_run_agentic_workflow", fake_agentic_workflow))
            stack.enter_context(patch.object(llm_service, "begin_token_tracking", lambda: None))
            stack.enter_context(patch.object(llm_service, "consume_token_usage", lambda: {}))
            stack.enter_context(
                patch.object(
                    settings,
                    "AGENTIC_FUNCTION_CALLING_ENABLED",
                    mode.startswith("agentic"),
                )
            )
            stack.enter_context(patch.object(settings, "AGENTIC_ALLOWED_CHANNELS", "widget"))

            service = ChatService(db=object())
            response = asyncio.run(
                service.process_chat(
                    ChatRequest(
                        user_id="regression-user",
                        message=str(dict(case.get("inputs") or {}).get("message") or ""),
                        locale=str(dict(case.get("inputs") or {}).get("locale") or "en-US"),
                    ),
                    channel="widget",
                )
            )
        actual_results[case_id] = response.model_dump(mode="json")
    return actual_results


def pytest_generate_tests(metafunc):
    if "case" not in metafunc.fixturenames:
        return
    cases = _get_cases()
    metafunc.parametrize("case", cases, ids=lambda case: case["id"])


@pytest.fixture(scope="module")
def chat_parser_fixture():
    return ChatParserFixture(parser_rules=_parser_rules(), alias_map=_alias_map())


def _parser_rules() -> ParserRuleSet:
    return build_rule_set(
        requested_field_patterns={
            "price": [r"\bprice\b", r"\bcost\b", r"\bhow much\b"],
            "stock": [r"\bstock\b", r"\bavailability\b", r"\bin stock\b", r"\bout of stock\b", r"\bavailable\b"],
            "image": [r"\bimage\b", r"\bpicture\b", r"\bphoto\b", r"\bpic\b"],
            "attributes": [r"\battribute\b", r"\battributes\b", r"\bspec\b", r"\bspecs\b", r"\bdetails\b"],
        },
        value_extract_patterns={
            "outer_diameter": [
                r"\bouter diameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b",
                r"\b(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\s+outer diameter\b",
                r"\bdiameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b",
            ],
            "ring_size": [r"\bring size(?: is|=| of)?\s+(?P<value>[a-z0-9.]+)\b"],
            "opal_color": [
                r"\b(?P<value>black|white|clear|blue|red|green|purple|pink|yellow|orange|silver|gold|rose gold)\s+opal color\b"
            ],
        },
        detection_attribute_order=["jewelry_type", "material", "threading", "finish", "design", "color"],
        allowed_attribute_filters=[
            "jewelry_type",
            "material",
            "threading",
            "finish",
            "design",
            "color",
            "gauge",
            "outer_diameter",
            "ring_size",
            "opal_color",
        ],
    )


def _alias_map() -> dict[str, dict[str, str]]:
    return {
        "jewelry_type": {
            "barbell": "barbell",
            "labret": "labret",
            "ring": "ring",
            "rings": "ring",
            "hoop": "ring",
        },
        "material": {
            "titanium": "titanium",
            "implant grade titanium": "titanium g23",
            "steel": "steel",
            "gold": "gold",
        },
        "finish": {
            "sterilized": "sterilized",
            "sterilised": "sterilized",
            "sterilization": "sterilized",
            "sterilisation": "sterilized",
        },
        "design": {
            "heart": "heart",
        },
        "color": {
            "black": "black",
            "blue": "blue",
            "gold": "gold",
            "opal": "opal",
            "opal color": "opal",
        },
        "stone": {
            "opal": "opal",
        },
    }


@pytest.mark.regression
def test_chat_ai_logic_cases(case, chat_parser_fixture) -> None:
    result = accuracy_eval.evaluate_case(
        case,
        actual_results=_get_actual_results(),
        parser_rules=chat_parser_fixture.parser_rules,
        alias_map=chat_parser_fixture.alias_map,
    )
    assert result["passed"], result["mismatches"]


def test_chat_ai_logic_suite_summary(chat_parser_fixture) -> None:
    try:
        cases = _get_cases()
    except Exception as exc:
        pytest.skip(f"DB-backed AI logic dataset unavailable: {exc}")
    summary = accuracy_eval.run_accuracy_suite(
        cases,
        actual_results=_get_actual_results(),
        parser_rules=chat_parser_fixture.parser_rules,
        alias_map=chat_parser_fixture.alias_map,
    )

    assert summary["total"] == len(cases)
    assert summary["failed"] == 0
    assert summary["by_kind"]["routing_decision"] >= 1
    assert summary["by_kind"]["detail_parse"] >= 1
    assert summary["by_kind"]["follow_up_generation"] >= 1
    assert summary["by_kind"]["response_contract"] >= 1
    assert summary["by_kind"]["context_contract"] >= 1
    assert summary["by_kind"]["long_context_contract"] >= 1
    assert summary["by_kind"]["adversarial_contract"] >= 1
    assert summary["by_suite"]["routing"] >= 1
    assert summary["by_suite"]["parser"] >= 1
    assert summary["by_suite"]["response"] >= 1
    assert summary["by_suite"]["long_context"] >= 1
    assert summary["by_suite"]["adversarial"] >= 1
    assert summary["by_focus_group"]["long_context"] >= 1
    assert summary["by_focus_group"]["adversarial"] >= 1
    assert summary["trend_summary"]["by_focus_group"]["long_context"] >= 1
    assert summary["trend_summary"]["by_focus_group"]["adversarial"] >= 1
