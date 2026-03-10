from __future__ import annotations

from uuid import uuid4

from app.schemas.chat import ChatHistoryMessage, ChatResponse, ProductCard


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
        follow_up_questions=["See more titanium labrets"],
        intent="browse_products",
        sources=[],
        debug={},
    )

    payload = response.model_dump(mode="json")

    assert "reply_text" not in payload
    assert "product_carousel" not in payload
    assert "follow_up_questions" not in payload
    assert [component["type"] for component in payload["components"]] == [
        "assistant_message",
        "product_cards",
        "quick_replies",
    ]


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
