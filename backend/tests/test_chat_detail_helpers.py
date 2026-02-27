from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.services.chat.detail_query_parser import DetailQueryParser
from app.services.chat.detail_response_builder import DetailResponseBuilder
from app.services.chat.product_detail_resolver import ProductDetailResolver


@dataclass
class _Card:
    id: object
    object_id: str
    sku: str
    name: str
    price: float
    currency: str
    stock_status: str
    image_url: str | None
    product_url: str | None
    attributes: dict


def _card(
    *,
    sku: str,
    name: str,
    price: float = 1.0,
    stock_status: str = "in_stock",
    image_url: str | None = None,
    attributes: dict | None = None,
) -> _Card:
    return _Card(
        id=uuid4(),
        object_id=sku,
        sku=sku,
        name=name,
        price=price,
        currency="USD",
        stock_status=stock_status,
        image_url=image_url,
        product_url=None,
        attributes=attributes or {},
    )


def test_detail_query_parser_extracts_fields_and_filters() -> None:
    parsed = DetailQueryParser.parse(
        user_text="price and stock for barbell black 25mm gauge with image",
        nlu_data={},
    )
    assert parsed.is_detail_request is True
    assert "price" in parsed.requested_fields
    assert "stock" in parsed.requested_fields
    assert "image" in parsed.requested_fields
    assert parsed.attribute_filters.get("jewelry_type") == "barbell"
    assert parsed.attribute_filters.get("color") == "black"
    assert parsed.attribute_filters.get("gauge") == "25mm"


def test_detail_query_parser_supports_opal_and_material_synonyms() -> None:
    parsed = DetailQueryParser.parse(
        user_text="Need opal color with implant grade titanium barbell",
        nlu_data={},
    )
    assert parsed.attribute_filters.get("color") == "opal"
    assert parsed.attribute_filters.get("material") == "titanium g23"
    assert parsed.attribute_filters.get("jewelry_type") == "barbell"


def test_detail_query_parser_filter_only_query_is_not_detail_mode() -> None:
    parsed = DetailQueryParser.parse(
        user_text="Give me a Labret with 14g with steel",
        nlu_data={},
    )
    assert parsed.is_detail_request is False
    assert parsed.attribute_filters.get("jewelry_type") == "labret"
    assert parsed.attribute_filters.get("gauge") == "14g"
    assert parsed.attribute_filters.get("material") == "steel"


def test_detail_resolver_filters_and_limits_top_matches() -> None:
    cards = [
        _card(
            sku="B-25-BLK",
            name="Barbell Black",
            attributes={"jewelry_type": "Barbell", "color": "Black", "gauge": "25mm"},
        ),
        _card(
            sku="B-25-WHT",
            name="Barbell White",
            attributes={"jewelry_type": "Barbell", "color": "White", "gauge": "25mm"},
        ),
        _card(
            sku="R-25-BLK",
            name="Ring Black",
            attributes={"jewelry_type": "Ring", "color": "Black", "gauge": "25mm"},
        ),
    ]
    resolver = ProductDetailResolver()
    resolved = resolver.resolve_detail_request(
        candidate_cards=cards,
        distance_by_id={str(cards[0].id): 0.05, str(cards[1].id): 0.08, str(cards[2].id): 0.01},
        requested_fields=["price", "stock"],
        attribute_filters={"jewelry_type": "barbell", "color": "black", "gauge": "25mm"},
        sku_token=None,
        nlu_product_code=None,
        max_matches=3,
        min_confidence=0.55,
    )
    assert len(resolved.matches) == 1
    assert resolved.matches[0].sku == "B-25-BLK"


def test_detail_response_builder_reports_missing_image() -> None:
    match = _card(
        sku="A-1",
        name="Example Product",
        image_url=None,
        attributes={"color": "Black", "gauge": "16g"},
    )
    payload = DetailResponseBuilder.build_detail_reply(
        matches=[match],
        requested_fields=["image", "attributes"],
        attribute_filters={"color": "black"},
        missing_fields_by_product={str(match.id): ["image"]},
        wants_image=True,
        max_matches=3,
    )
    assert "Image: unavailable" in payload.reply_text
    assert payload.card_policy_reason == "image_requested"
    assert len(payload.product_carousel) == 1
    assert "Show price for SKU A-1." in payload.follow_up_questions
    assert "Show stock for SKU A-1." in payload.follow_up_questions
    assert "Some items have no image. Ask for price/stock instead." in payload.follow_up_questions


def test_detail_response_builder_multi_match_followups_use_context() -> None:
    first = _card(
        sku="B-25-BLK",
        name="Black Barbell 25mm",
        image_url="https://example.com/b-25-blk.jpg",
        attributes={"jewelry_type": "Barbell", "color": "Black", "gauge": "25mm"},
    )
    second = _card(
        sku="B-25-WHT",
        name="White Barbell 25mm",
        image_url="https://example.com/b-25-wht.jpg",
        attributes={"jewelry_type": "Barbell", "color": "White", "gauge": "25mm"},
    )
    payload = DetailResponseBuilder.build_detail_reply(
        matches=[first, second],
        requested_fields=["attributes"],
        attribute_filters={"jewelry_type": "barbell"},
        missing_fields_by_product={},
        wants_image=False,
        max_matches=3,
    )
    assert payload.card_policy_reason == "multiple_matches"
    assert payload.product_carousel
    assert "Show full details for SKU B-25-BLK." in payload.follow_up_questions
    assert "Compare SKU B-25-BLK and SKU B-25-WHT." in payload.follow_up_questions
    assert "Show in-stock items only." in payload.follow_up_questions
