from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.config import settings
from app.schemas.chat import KnowledgeSource
from app.services.chat.components.builders.clarify import ClarifyComponent
from app.services.chat.components.builders.error import ErrorComponent
from app.services.ai.llm_service import llm_service
from app.services.chat.components.builders.knowledge_answer import KnowledgeAnswerComponent
from app.services.chat.components.builders.product_cards import ProductCardsComponent
from app.services.chat.components.builders.product_detail import ProductDetailComponent
from app.services.chat.components.builders.query_summary import QuerySummaryComponent
from app.services.chat.components.builders.recommendations import RecommendationsComponent
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentSource, ComponentType


def _sample_products() -> list[CanonicalProduct]:
    return [
        CanonicalProduct(
            product_id=uuid4(),
            sku="SKU-1",
            title="Ring One",
            price=Decimal("12.50"),
            currency="USD",
            in_stock=True,
            stock_qty=5,
            material="Steel",
            gauge="16g",
            image_url="https://example.com/1.jpg",
            attributes={"material": "Steel", "gauge": "16g"},
            product_url="https://example.com/p1",
        ),
        CanonicalProduct(
            product_id=uuid4(),
            sku="SKU-2",
            title="Ring Two",
            price=Decimal("20.00"),
            currency="USD",
            in_stock=False,
            stock_qty=0,
            material="Titanium",
            gauge="14g",
            image_url="https://example.com/2.jpg",
            attributes={"material": "Titanium", "gauge": "14g"},
            product_url="https://example.com/p2",
        ),
    ]


def _sample_context() -> ComponentContext:
    products = _sample_products()
    return ComponentContext(
        user_text="show ring products",
        locale="en-US",
        workflow="catalog",
        query_summary="show products",
        source=ComponentSource.SQL,
        selected_components=[ComponentType.QUERY_SUMMARY],
        canonical_products=products,
        recommendations=[products[1]],
        knowledge_sources=[
            KnowledgeSource(
                source_id="kb-1",
                title="Shipping",
                content_snippet="Ships in 3-5 days",
                relevance=0.9,
            )
        ],
        knowledge_answer="Shipping takes 3-5 days.",
        result_count=len(products),
        ambiguity_reason="need_more_context",
        error_message="component error",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder_cls, expected_type, expected_key",
    [
        (QuerySummaryComponent, ComponentType.QUERY_SUMMARY, "text"),
        (ProductCardsComponent, ComponentType.PRODUCT_CARDS, "cards"),
        (ProductDetailComponent, ComponentType.PRODUCT_DETAIL, "product"),
        (RecommendationsComponent, ComponentType.RECOMMENDATIONS, "items"),
        (ClarifyComponent, ComponentType.CLARIFY, "message"),
        (KnowledgeAnswerComponent, ComponentType.KNOWLEDGE_ANSWER, "answer"),
        (ErrorComponent, ComponentType.ERROR, "message"),
    ],
)
async def test_builder_outputs_shape(builder_cls, expected_type: ComponentType, expected_key: str) -> None:
    context = _sample_context()
    component = await builder_cls().build(context)
    assert str(component.type.value) == expected_type.value
    assert expected_key in component.data
    if expected_key == "cards":
        assert component.data["cards"][0]["master_code"] == "Ring One"
    elif expected_key == "product":
        assert component.data["product"]["master_code"] == "Ring One"
    elif expected_key == "items":
        assert component.data["items"][0]["master_code"] == "Ring Two"


@pytest.mark.asyncio
async def test_clarify_builder_hides_questions_and_suggestions_from_public_payload() -> None:
    context = _sample_context()
    context.ambiguity_reason = "knowledge_needs_clarification"
    context.debug = {
        "clarify_message": "I want to give you the right answer, but I need one more detail.",
        "clarify_questions": [
            "Which policy or contact detail do you need?",
            "Is this for sales or support?",
        ],
        "clarify_suggestions": [
            "How can I contact you?",
            "What is your shipping policy?",
            "What is your refund policy?",
            "extra item should be trimmed",
        ],
    }

    component = await ClarifyComponent().build(context)

    assert component.data["message"] == "I want to give you the right answer, but I need one more detail."
    assert "questions" not in component.data
    assert "suggestions" not in component.data


@pytest.mark.asyncio
async def test_clarify_builder_can_use_contextual_llm_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _sample_context()
    context.ambiguity_reason = "need_more_context"
    context.error_message = None
    context.debug = {}

    async def fake_generate_chat_json(**kwargs):
        return {"message": "Which size are you looking for?"}

    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    component = await ClarifyComponent().build(context)

    assert component.data["message"] == "Which size are you looking for?"


@pytest.mark.asyncio
async def test_error_builder_can_use_contextual_llm_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _sample_context()
    context.error_message = None

    async def fake_generate_chat_json(**kwargs):
        return {"message": "I ran into an issue with that request. Please try again in a moment."}

    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", fake_generate_chat_json)

    component = await ErrorComponent().build(context)

    assert component.data["message"] == "I ran into an issue with that request. Please try again in a moment."


@pytest.mark.asyncio
async def test_contextual_component_copy_falls_back_to_tone_variants_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _sample_context()
    context.error_message = None
    context.debug = {}

    async def broken_generate_chat_json(**kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(settings, "CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED", True)
    monkeypatch.setattr(llm_service, "generate_chat_json", broken_generate_chat_json)

    clarify_component = await ClarifyComponent().build(context)
    error_component = await ErrorComponent().build(context)

    assert clarify_component.data["message"]
    assert error_component.data["message"]
