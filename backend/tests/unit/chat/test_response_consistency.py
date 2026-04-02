import pytest

from uuid import uuid4

import pytest

from app.schemas.chat import ChatComponent, ChatResponse, ChatRouting, ProductCard
from app.services.chat.presentation import component_contract
from app.services.chat.presentation.response_consistency import ResponseConsistencyPolicy


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
