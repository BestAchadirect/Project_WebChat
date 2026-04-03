from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.prompts.response_copy import pick_response_copy
from app.services.chat.presentation import product_presentation
from app.services.chat.components.canonical_model import CanonicalProduct


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


def test_pick_response_copy_formats_registry_values() -> None:
    text = pick_response_copy(
        key="recommendation_summary.complementary",
        user_text="need a matching top",
        values={
            "focus_label": "compatible tops",
            "anchor_type": "barbell",
            "recommendation_label": "Top",
            "benefit_text": "easy to mix and match",
        },
    )

    assert "compatible tops" in text.lower()
    assert "barbell" in text.lower()


def test_recommendation_summary_reply_stays_concise_and_contextual() -> None:
    products = [
        _canonical_product(
            sku="TOP-1",
            title="Threadless Heart Top",
            attributes={"jewelry_type": "Top", "threading": "threadless", "gauge": "16g", "material": "Titanium"},
        ),
    ]

    text = product_presentation.build_recommendation_summary_reply(
        products=products,
        attribute_filters={"jewelry_type": "Barbell"},
        recommendation_mode="complementary_items",
        recommendation_label="Top",
        user_text="I need a matching top",
    )

    lowered = text.lower()
    assert "top" in lowered
    assert "barbell" in lowered
    assert any(phrase in lowered for phrase in ("i found", "here are", "i pulled up"))


def test_product_match_reply_uses_upsell_copy_when_products_are_available() -> None:
    products = [
        _canonical_product(
            sku="TI-1",
            title="Titanium Labret",
            attributes={"master_code": "TI-1", "material": "Titanium", "jewelry_type": "Labret"},
        )
    ]

    text = product_presentation.build_product_match_reply(
        attribute_filters={"material": "Titanium", "jewelry_type": "Labret"},
        user_text="show me titanium labrets",
        products=products,
    )

    lowered = text.lower()
    assert "titanium" in lowered
    assert "labret" in lowered
    assert any(phrase in lowered for phrase in ("lightweight", "skin-friendly", "everyday choice"))
