from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.presentation import product_presentation, reply_tone


def _canonical_product(*, sku: str, title: str, attributes: dict | None = None) -> CanonicalProduct:
    attrs = attributes or {}
    return CanonicalProduct(
        product_id=uuid4(),
        sku=sku,
        title=title,
        price=Decimal("12.50"),
        currency="USD",
        in_stock=True,
        stock_qty=5,
        material=str(attrs.get("material") or "Steel"),
        gauge=str(attrs.get("gauge") or "14g"),
        image_url=None,
        description=title,
        attributes=attrs,
        product_url="https://example.com/product",
    )


@pytest.mark.asyncio
async def test_product_match_reply_uses_contextual_copy_when_products_are_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    products = [
        _canonical_product(
            sku="TI-1",
            title="Titanium Labret",
            attributes={"master_code": "TI-1", "material": "Titanium", "jewelry_type": "Labret"},
        )
    ]

    async def fake_generate_contextual_reply(*, kind, reply_language, payload):
        assert kind == "product"
        assert reply_language == "en-US"
        assert payload["focus_label"] == "titanium labret options"
        return "Titanium labret options are a lightweight and skin-friendly fit."

    monkeypatch.setattr(product_presentation, "generate_contextual_reply", fake_generate_contextual_reply)

    text = await product_presentation.build_product_match_reply(
        attribute_filters={"material": "Titanium", "jewelry_type": "Labret"},
        user_text="show me titanium labrets",
        products=products,
        locale="en-US",
    )

    lowered = text.lower()
    assert "titanium" in lowered
    assert "labret" in lowered
    assert "skin-friendly" in lowered


def test_compose_variant_is_deterministic_without_recent_history() -> None:
    variants = ["A", "B", "C"]
    first = reply_tone.compose_variant(
        user_text="show titanium labrets",
        key="catalog:default_reply",
        variants=variants,
        humanizer_enabled=True,
    )
    second = reply_tone.compose_variant(
        user_text="show titanium labrets",
        key="catalog:default_reply",
        variants=variants,
        humanizer_enabled=True,
    )
    assert first.variant_id == second.variant_id
    assert first.text == second.text


def test_compose_variant_anti_repeat_skips_recent_variant_when_available() -> None:
    variants = ["Option A", "Option B", "Option C"]
    base = reply_tone.compose_variant(
        user_text="show titanium labrets",
        key="clarify:structured_no_match",
        variants=variants,
        humanizer_enabled=True,
    )
    recent = [{"key": base.key, "style": base.style, "variant_id": base.variant_id}]
    next_choice = reply_tone.compose_variant(
        user_text="show titanium labrets",
        key="clarify:structured_no_match",
        variants=variants,
        recent=recent,
        anti_repeat_window=4,
        humanizer_enabled=True,
    )
    assert next_choice.variant_id != base.variant_id
    assert next_choice.anti_repeat_applied is True


def test_infer_style_maps_representative_inputs() -> None:
    assert reply_tone.infer_style("hey can u help me") == "casual"
    assert reply_tone.infer_style("show me titanium") == "direct"
    assert reply_tone.infer_style("Could you share your shipping policy?") == "neutral"


def test_strip_filler_removes_robotic_lead_ins() -> None:
    assert reply_tone.strip_filler("Here is what I found: We have options.") == "We have options."
    assert reply_tone.strip_filler("Understood. I can help with that.") == "I can help with that."
