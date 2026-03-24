from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.services.chat.parsing.detail_query_parser import DetailQueryParser
from app.services.chat.parsing.parser_rule_types import build_rule_set
from app.services.chat.presentation.detail_response_builder import DetailResponseBuilder
from app.services.chat.retrieval.product_detail_resolver import ProductDetailResolver


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


def _db_rules():
    return build_rule_set(
        requested_field_patterns={
            "price": [r"\bprice\b", r"\bcost\b", r"\bhow much\b"],
            "stock": [r"\bstock\b", r"\bavailability\b", r"\bin stock\b", r"\bout of stock\b", r"\bavailable\b"],
            "image": [r"\bimage\b", r"\bpicture\b", r"\bphoto\b", r"\bpic\b"],
            "attributes": [r"\battribute\b", r"\battributes\b", r"\bspec\b", r"\bspecs\b", r"\bdetails\b"],
        },
        value_extract_patterns={
            "outer_diameter": [
                r"\bouter diameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b",
                r"\b(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\s+outer diameter\b",
                r"\bdiameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b",
            ],
            "ring_size": [r"\bring size(?: is|=| of)?\s+(?P<value>[a-z0-9.]+)\b"],
            "opal_color": [
                r"\b(?P<value>black|white|clear|blue|red|green|purple|pink|yellow|orange|silver|gold|rose gold)\s+opal color\b"
            ],
        },
        detection_attribute_order=["jewelry_type", "material", "threading", "finish", "design", "color"],
        allowed_attribute_filters=["jewelry_type", "material", "threading", "finish", "design", "color", "gauge", "outer_diameter", "ring_size", "opal_color"],
    )


def _db_alias_map() -> dict[str, dict[str, str]]:
    return {
        "jewelry_type": {
            "barbell": "barbell",
            "labret": "labret",
            "ring": "ring",
            "hoop": "ring",
        },
        "material": {
            "titanium": "titanium",
            "implant grade titanium": "titanium g23",
            "steel": "steel",
        },
        "finish": {
            "sterilized": "sterilized",
            "sterilised": "sterilized",
            "sterilization": "sterilized",
            "sterilisation": "sterilized",
        },
        "design": {
            "heart": "heart",
        },
        "color": {
            "black": "black",
            "blue": "blue",
            "opal": "opal",
            "opal color": "opal",
        },
        "stone": {
            "opal": "opal",
        },
    }


def test_detail_query_parser_extracts_fields_and_filters() -> None:
    parsed = DetailQueryParser.parse(
        user_text="price and stock for barbell black 25mm gauge with image",
        nlu_data={},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
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
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )
    assert parsed.attribute_filters.get("color") == "opal"
    assert parsed.attribute_filters.get("material") == "titanium g23"
    assert parsed.attribute_filters.get("jewelry_type") == "barbell"


def test_detail_query_parser_infers_plain_opal_from_alias_map_even_without_detection_order() -> None:
    rules = build_rule_set(
        requested_field_patterns=_db_rules().requested_field_patterns,
        value_extract_patterns=_db_rules().value_extract_patterns,
        detection_attribute_order=["jewelry_type", "material", "threading", "finish", "design"],
        allowed_attribute_filters=["stone", "color", "opal_color", "finish", "material"],
    )
    parsed = DetailQueryParser.parse(
        user_text="Do you have sterilization with opal?",
        nlu_data={},
        alias_map=_db_alias_map(),
        parser_rules=rules,
    )
    assert parsed.attribute_filters.get("finish") is None
    assert parsed.attribute_filters.get("stone") == "opal"
    assert parsed.semantic_hints == []


def test_detail_query_parser_does_not_force_sterilization_into_finish_without_exact_wording() -> None:
    alias_map = _db_alias_map()
    alias_map.pop("finish", None)
    parsed = DetailQueryParser.parse(
        user_text="Do you have sterilization with opal?",
        nlu_data={},
        alias_map=alias_map,
        parser_rules=_db_rules(),
    )

    assert parsed.attribute_filters.get("finish") is None
    assert any(
        parsed.attribute_filters.get(key) == "opal"
        for key in ("stone", "color", "opal_color")
    )


def test_detail_query_parser_filter_only_query_is_not_detail_mode() -> None:
    parsed = DetailQueryParser.parse(
        user_text="Give me a Labret with 14g with steel",
        nlu_data={},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )
    assert parsed.is_detail_request is False
    assert parsed.attribute_filters.get("jewelry_type") == "labret"
    assert parsed.attribute_filters.get("gauge") == "14g"
    assert parsed.attribute_filters.get("material") == "steel"


def test_detail_query_parser_extracts_extended_attribute_filters() -> None:
    parsed = DetailQueryParser.parse(
        user_text="Show sterilized heart ring with 8mm outer diameter and ring size 7 in blue opal color",
        nlu_data={},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )

    assert parsed.attribute_filters.get("finish") == "sterilized"
    assert parsed.attribute_filters.get("design") == "heart"
    assert parsed.attribute_filters.get("jewelry_type") == "ring"
    assert parsed.attribute_filters.get("outer_diameter") == "8mm"
    assert parsed.attribute_filters.get("ring_size") == "7"
    assert parsed.attribute_filters.get("opal_color") == "blue"


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
    assert "I found 1 matching product." in payload.reply_text
    assert "Image: unavailable" in payload.reply_text
    assert payload.card_policy_reason == "single_match_text_only"
    assert len(payload.product_carousel) == 1
    assert payload.carousel_msg == "Master code Example Product has 1 variant. Expand to view variant details."
    assert payload.follow_up_questions == []


def test_detail_response_builder_multi_match_followups_use_context() -> None:
    first = _card(
        sku="B-25-BLK",
        name="BLK466",
        image_url="https://example.com/b-25-blk.jpg",
        attributes={"master_code": "BLK466", "jewelry_type": "Barbell", "color": "Black", "gauge": "25mm"},
    )
    second = _card(
        sku="B-25-WHT",
        name="BLK466",
        image_url="https://example.com/b-25-wht.jpg",
        attributes={"master_code": "BLK466", "jewelry_type": "Barbell", "color": "White", "gauge": "25mm"},
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
    assert payload.carousel_msg == "Master code BLK466 has 2 variants. Expand to view variant details."
    assert payload.product_carousel
    assert "Key details:" in payload.reply_text
    assert "[JEWELRY TYPE] Barbell" in payload.reply_text
    assert "Attributes:" not in payload.reply_text
    assert "Top master code: [MASTER] BLK466" in payload.reply_text
    assert payload.follow_up_questions == []


def test_detail_response_builder_attribute_focus_highlights_filters() -> None:
    first = _card(
        sku="BLK466-F02A12",
        name="BLK466",
        attributes={"color": "Gold", "gauge": "16g", "jewelry_type": "Labret", "material": "Gold"},
    )
    second = _card(
        sku="BLK466-F04A12",
        name="BLK466",
        attributes={"color": "Gold", "gauge": "16g", "jewelry_type": "Labret", "material": "Gold"},
    )
    payload = DetailResponseBuilder.build_detail_reply(
        matches=[first, second],
        requested_fields=["attributes"],
        attribute_filters={"material": "gold", "color": "gold"},
        missing_fields_by_product={},
        wants_image=False,
        max_matches=3,
    )
    assert "Key details:" in payload.reply_text
    assert "[MATERIAL] Gold" in payload.reply_text
    assert "[COLOR] Gold" in payload.reply_text
    assert "Top master code: [MASTER] BLK466" in payload.reply_text
    assert "Attributes:" not in payload.reply_text
    assert payload.carousel_msg == "Master code BLK466 has 2 variants. Expand to view variant details."


def test_detail_response_builder_image_focus_groups_master_without_sku_lines() -> None:
    first = _card(
        sku="BLK466-F02A12",
        name="BLK466",
        image_url="https://example.com/blk466-a.jpg",
        attributes={"master_code": "BLK466", "material": "Titanium G23"},
    )
    second = _card(
        sku="BLK466-F04A12",
        name="BLK466",
        image_url="https://example.com/blk466-b.jpg",
        attributes={"master_code": "BLK466", "material": "Titanium G23"},
    )
    payload = DetailResponseBuilder.build_detail_reply(
        matches=[first, second],
        requested_fields=["image"],
        attribute_filters={"material": "titanium g23"},
        missing_fields_by_product={},
        wants_image=True,
        max_matches=3,
    )

    assert "master code BLK466" in payload.reply_text
    assert "Image: https://example.com/blk466-a.jpg" in payload.reply_text
    assert "SKU:" not in payload.reply_text
    assert payload.card_policy_reason == "image_master_grouped"
    assert len(payload.product_carousel) == 1
