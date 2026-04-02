from __future__ import annotations

from uuid import uuid4

from app.schemas.chat import (
    ChatHistoryMessage,
    ChatResponse,
    ChatRouting,
    ProductCard,
    assistant_message_component,
    product_cards_component,
    quick_replies_component,
)


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
