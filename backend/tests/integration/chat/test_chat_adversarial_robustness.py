from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatRequest
from app.core.config import settings
from app.services.chat.observability.accuracy_eval import evaluate_case
from app.services.chat.routing.contracts import UnderstandingResult
from app.services.chat.service import ChatService
from tests.fixtures.chat import (
    DummyConversation,
    build_component_pipeline_result,
    load_json_dataset,
    patch_chat_service_lifecycle,
)


DATASET_PATH = Path(__file__).resolve().parents[2] / "regression" / "data" / "chat_adversarial_cases.json"
CASES = load_json_dataset(DATASET_PATH, infer_suite=True)

pytestmark = [pytest.mark.regression, pytest.mark.adversarial]


def _understanding_from_case(case: dict[str, object]):
    fixture = dict(case.get("runtime_fixture") or {})
    understanding = dict(fixture.get("understanding") or {})
    inputs = dict(case.get("inputs") or {})
    return UnderstandingResult(
        normalized_text=str(inputs.get("message") or "").strip().lower(),
        locale=str(inputs.get("locale") or "en-US"),
        channel="widget",
        sku_tokens=[],
        workflow_hypothesis=str(understanding.get("workflow_hypothesis") or "off_topic"),
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


def pytest_generate_tests(metafunc):
    if "case" not in metafunc.fixturenames:
        return
    metafunc.parametrize("case", CASES, ids=lambda case: case["id"])


@pytest.mark.asyncio
async def test_adversarial_cases_stay_boundaried(
    monkeypatch: pytest.MonkeyPatch,
    case: dict[str, object],
) -> None:
    fixture = dict(case.get("runtime_fixture") or {})
    component_response = dict(fixture.get("component_response") or {})
    understanding = _understanding_from_case(case)

    async def fake_understanding(**kwargs):
        del kwargs
        return understanding

    async def fake_component_pipeline(self, *, request, conversation_id, run_id, **kwargs):
        del self, kwargs
        return build_component_pipeline_result(
            request=request,
            conversation_id=conversation_id,
            reply_text=str(component_response.get("reply_text") or ""),
            response_workflow=str(component_response.get("workflow") or "fallback"),
            source=str(component_response.get("source") or "error"),
            response_debug=dict(component_response.get("debug") or {}),
            sources=list(component_response.get("sources") or []),
            product_carousel=list(component_response.get("product_carousel") or []),
        )

    patch_chat_service_lifecycle(
        monkeypatch,
        conversation=DummyConversation(conversation_id=77),
    )
    monkeypatch.setattr(settings, "AGENTIC_FUNCTION_CALLING_ENABLED", False)
    monkeypatch.setattr("app.services.chat.harness.dependencies.build_understanding_result", fake_understanding)
    monkeypatch.setattr(ChatService, "_run_component_pipeline", fake_component_pipeline)

    service = ChatService(db=object())
    inputs = dict(case.get("inputs") or {})
    response = await service.process_chat(
        ChatRequest(
            user_id="adversarial-user",
            message=str(inputs.get("message") or ""),
            locale=str(inputs.get("locale") or "en-US"),
        ),
        channel="widget",
    )

    payload = response.model_dump(mode="json")
    assert response.routing.workflow == str(component_response.get("workflow") or "fallback")
    assert not response.product_carousel
    assert not response.sources

    evaluated = evaluate_case(case, actual_results={case["id"]: payload})
    assert evaluated["passed"], evaluated["mismatches"]
