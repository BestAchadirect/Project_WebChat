from __future__ import annotations

from uuid import uuid4

import pytest

from app.schemas.chat import (
    ChatComponent,
    ChatHistoryMessage,
    ChatResponse,
    ChatRouting,
    ProductCard,
    assistant_message_component,
    product_cards_component,
    quick_replies_component,
)
from app.services.chat.presentation import component_contract
from app.services.chat.presentation.response_consistency import ResponseConsistencyPolicy
from app.services.chat.runtime.agentic_adapter import build_agentic_response
from app.services.chat.agentic.orchestrator import AgentRunResult


def _product_card() -> ProductCard:
    return ProductCard(
        id=uuid4(),
        object_id="OBJ-1",
        sku="SKU-1",
        legacy_sku=[],
        name="Titanium Labret",
        description="Mirror finish",
        price=12.5,
        currency="USD",
        stock_status="in_stock",
        image_url=None,
        product_url=None,
        attributes={"material": "Titanium"},
    )


@pytest.mark.regression
@pytest.mark.asyncio
async def test_reply_consistency_rewrites_not_found_when_products_exist() -> None:
    async def passthrough(text: str) -> str:
        return text

    fixed = await ResponseConsistencyPolicy.ensure_consistent_reply(
        reply_data={
            "reply": "I couldn't find specific 16 gauge options in our current offerings.",
            "carousel_hint": "",
        },
        has_products=True,
        localize_text=passthrough,
    )

    assert fixed["reply"] == ResponseConsistencyPolicy.DEFAULT_PRODUCT_REPLY
    assert fixed["carousel_hint"] == ResponseConsistencyPolicy.DEFAULT_CAROUSEL_HINT


@pytest.mark.regression
@pytest.mark.asyncio
async def test_cached_response_normalization_keeps_existing_hint() -> None:
    async def passthrough(text: str) -> str:
        return text

    reply, hint = await ResponseConsistencyPolicy.normalize_cached_response(
        reply_text="Could not find matching products.",
        carousel_msg="Already has hint",
        has_products=True,
        localize_text=passthrough,
    )

    assert reply == ResponseConsistencyPolicy.DEFAULT_PRODUCT_REPLY
    assert hint == "Already has hint"


def test_response_adapter_prefers_components_over_legacy_fields() -> None:
    card = _product_card()
    response = ChatResponse(
        conversation_id=1,
        reply_text="legacy reply",
        carousel_msg="legacy hint",
        product_carousel=[card],
        routing=ChatRouting(workflow="catalog", execution_mode="component", needs_products=True),
        sources=[],
        debug={},
        components=[
            ChatComponent(type="assistant_message", data={"text": "canonical reply"}),
            ChatComponent(
                type="product_cards",
                data={
                    "cards": [
                        {
                            "product_id": str(card.id),
                            "sku": card.sku,
                            "title": card.name,
                            "price": card.price,
                            "currency": card.currency,
                            "in_stock": True,
                            "attributes": dict(card.attributes or {}),
                        }
                    ]
                },
            ),
        ],
    )

    assert component_contract.assistant_text_from_response(response) == "canonical reply"
    assert [item.id for item in component_contract.product_cards_from_response(response)] == [card.id]


def test_chat_response_serializes_as_component_first_contract() -> None:
    response = ChatResponse(
        conversation_id=1,
        reply_text="I found a match.",
        carousel_msg="Matching products are shown below.",
        product_carousel=[_product_card()],
        routing=ChatRouting(workflow="catalog", execution_mode="component", needs_products=True),
        sources=[],
        debug={},
        components=[
            {
                "type": "quick_replies",
                "data": {"items": ["See more titanium labrets"]},
            }
        ],
    )

    payload = response.model_dump(mode="json")

    assert "reply_text" not in payload
    assert "product_carousel" not in payload
    assert "follow_up_questions" not in payload
    assert [component["type"] for component in payload["components"]] == [
        "assistant_message",
        "quick_replies",
        "product_cards",
    ]


def test_chat_response_marks_legacy_fields_as_deprecated() -> None:
    schema = ChatResponse.model_json_schema()

    assert schema["properties"]["reply_text"]["deprecated"] is True
    assert schema["properties"]["carousel_msg"]["deprecated"] is True
    assert schema["properties"]["product_carousel"]["deprecated"] is True


def test_chat_history_message_synthesizes_components_from_legacy_storage() -> None:
    message = ChatHistoryMessage(
        role="assistant",
        content="I found a match.",
        product_data=[_product_card().model_dump(mode="json")],
    )

    payload = message.model_dump(mode="json")

    assert "product_data" not in payload
    assert [component["type"] for component in payload["components"]] == [
        "assistant_message",
        "product_cards",
    ]


def test_component_helpers_build_canonical_payloads() -> None:
    card = _product_card()

    assistant = assistant_message_component("  Hello there  ")
    products = product_cards_component([card])
    quick_replies = quick_replies_component([" Show more titanium labrets ", ""])

    assert assistant is not None
    assert assistant.model_dump(mode="json") == {
        "type": "assistant_message",
        "data": {"text": "Hello there"},
    }
    assert products is not None
    assert products.model_dump(mode="json") == {
        "type": "product_cards",
        "data": {
            "cards": [
                {
                    "product_id": str(card.id),
                    "object_id": "OBJ-1",
                    "sku": "SKU-1",
                    "title": "Titanium Labret",
                    "description": "Mirror finish",
                    "price": 12.5,
                    "currency": "USD",
                    "in_stock": True,
                    "stock_qty": None,
                    "image_url": None,
                    "product_url": None,
                    "material": "Titanium",
                    "gauge": "",
                    "attributes": {"material": "Titanium"},
                }
            ]
        },
    }
    assert quick_replies is not None
    assert quick_replies.model_dump(mode="json") == {
        "type": "quick_replies",
        "data": {"items": ["Show more titanium labrets"]},
    }


def test_agentic_response_round_trips_through_shared_component_contract() -> None:
    card = _product_card()
    response = build_agentic_response(
        conversation_id=7,
        routing=ChatRouting(workflow="catalog", execution_mode="agentic", needs_products=True),
        query_summary="show titanium labrets",
        agentic_result=AgentRunResult(
            final_reply="Here are titanium labrets that match.",
            used_tools=True,
            product_carousel=[card],
            follow_up_questions=["Show more titanium labrets"],
            trace=[{"tool": "search_products", "status": "ok"}],
        ),
    )

    assert component_contract.assistant_text_from_response(response) == "Here are titanium labrets that match."
    assert [item.id for item in component_contract.product_cards_from_response(response)] == [card.id]
    assert component_contract.follow_up_questions_from_response(response) == ["Show more titanium labrets"]
    assert [component.type.value for component in response.components] == [
        "assistant_message",
        "product_cards",
        "quick_replies",
    ]
