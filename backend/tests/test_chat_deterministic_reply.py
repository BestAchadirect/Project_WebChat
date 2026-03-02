from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")

from app.schemas.chat import ChatResponse, ProductCard
from app.services.chat import deterministic_reply


def _card(sku: str, name: str) -> ProductCard:
    return ProductCard(
        id=uuid4(),
        object_id=sku,
        sku=sku,
        legacy_sku=[],
        name=name,
        price=10.0,
        currency="USD",
        stock_status="in_stock",
        image_url=None,
        product_url=None,
        attributes={},
    )


def test_build_product_list_filter_phrase_and_reply_data() -> None:
    phrase = deterministic_reply.build_product_list_filter_phrase(
        {"jewelry_type": "Labret", "material": "Steel", "gauge": "16g"}
    )
    assert "Labret items" in phrase
    assert "in Steel" in phrase
    assert "(16g)" in phrase

    payload = deterministic_reply.build_deterministic_product_reply_data(
        products=[_card("A-1", "Alpha"), _card("A-2", "Beta")],
        attribute_filters={"material": "Steel"},
    )
    assert "matching products" in payload["reply"]
    assert payload["carousel_hint"] == "Matching products are shown below."


def test_build_route_fallback_text_uses_route_kind() -> None:
    assert deterministic_reply.build_route_fallback_text(
        route_kind="knowledge_query", reason=""
    ).startswith("I can share a brief answer")
    assert deterministic_reply.build_route_fallback_text(
        route_kind="browse_products", reason=""
    ).startswith("I can only provide a basic product result")


@pytest.mark.asyncio
async def test_build_route_fallback_response_adds_clarify_follow_up_for_vague_route() -> None:
    async def fake_render(**kwargs):
        return ChatResponse(
            conversation_id=kwargs["conversation_id"],
            reply_text=kwargs["reply_data"]["reply"],
            carousel_msg=kwargs["reply_data"].get("carousel_hint"),
            product_carousel=kwargs["product_carousel"],
            follow_up_questions=kwargs["follow_up_questions"],
            intent=kwargs["route"],
            sources=[],
            debug=kwargs["debug"],
        )

    service = SimpleNamespace(_response_renderer=SimpleNamespace(render=fake_render))
    response = await deterministic_reply.build_route_fallback_response(
        service=service,
        conversation_id=1,
        route_kind="vague",
        reason="external_call_budget",
        user_text="help",
        reply_language="en-US",
        target_currency="USD",
        debug_meta={},
        product_carousel=[],
    )
    assert response.follow_up_questions == ["Share product type, material, or SKU to continue."]
