from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4
from types import SimpleNamespace

import pytest

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
    in_stock: bool
    stock_status: str
    image_url: str | None
    product_url: str | None
    attributes: dict


def _card(
    *,
    sku: str,
    name: str,
    price: float = 1.0,
    in_stock: bool = True,
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
        in_stock=in_stock,
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


def _fake_detail_inference(
    *,
    requested_fields: list[str] | None = None,
    attribute_filters: dict[str, str] | None = None,
    wants_image: bool = False,
    semantic_hints: list[str] | None = None,
    unknown_terms: list[str] | None = None,
    clarify_focus: str = "",
    confidence: float = 0.91,
    debug: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        requested_fields=list(requested_fields or []),
        attribute_filters=dict(attribute_filters or {}),
        wants_image=wants_image,
        semantic_hints=list(semantic_hints or []),
        unknown_terms=list(unknown_terms or []),
        clarify_focus=clarify_focus,
        confidence=confidence,
        debug=dict(debug or {}),
    )


@pytest.mark.asyncio
async def test_detail_query_parser_extracts_fields_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return _fake_detail_inference(
            requested_fields=["price", "stock", "image", "attributes"],
            attribute_filters={"jewelry_type": "barbell", "color": "black", "gauge": "25mm"},
            wants_image=True,
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="price and stock for barbell black 25mm gauge with image",
        nlu_data={"workflow": "catalog"},
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


@pytest.mark.asyncio
async def test_detail_query_parser_supports_explicit_opal_color_and_material_synonyms(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return _fake_detail_inference(
            requested_fields=["attributes"],
            attribute_filters={"opal_color": "blue", "material": "titanium g23", "jewelry_type": "barbell"},
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="Need blue opal color with implant grade titanium barbell",
        nlu_data={"workflow": "catalog"},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )
    assert parsed.attribute_filters.get("opal_color") == "blue"
    assert parsed.attribute_filters.get("material") == "titanium g23"
    assert parsed.attribute_filters.get("jewelry_type") == "barbell"


@pytest.mark.asyncio
async def test_detail_query_parser_does_not_infer_plain_opal_without_explicit_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return _fake_detail_inference(
            requested_fields=["attributes"],
            attribute_filters={},
            semantic_hints=[],
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="Do you have sterilization with opal?",
        nlu_data={"workflow": "catalog"},
        alias_map={key: value for key, value in _db_alias_map().items() if key not in {"color", "stone", "finish"}},
        parser_rules=_db_rules(),
    )
    assert parsed.attribute_filters.get("finish") is None
    assert parsed.attribute_filters.get("stone") is None
    assert parsed.attribute_filters.get("opal_color") is None
    assert parsed.semantic_hints == []


@pytest.mark.asyncio
async def test_detail_query_parser_does_not_force_sterilization_into_finish_without_exact_wording(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return _fake_detail_inference(
            requested_fields=["attributes"],
            attribute_filters={},
            semantic_hints=[],
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="Do you have sterilization with opal?",
        nlu_data={"workflow": "catalog"},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )

    assert parsed.attribute_filters.get("finish") is None
    assert all(parsed.attribute_filters.get(key) is None for key in ("stone", "color", "opal_color"))


@pytest.mark.asyncio
async def test_detail_query_parser_uses_unknown_terms_to_request_specific_product(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return _fake_detail_inference(
            requested_fields=[],
            attribute_filters={},
            semantic_hints=[],
            unknown_terms=["sterilized"],
            clarify_focus="",
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="sterilized with opal",
        nlu_data={"workflow": "catalog"},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )

    assert parsed.unknown_terms == ["sterilized"]
    assert parsed.clarify_focus == "detail_request_needs_specific_product"


@pytest.mark.asyncio
async def test_detail_query_parser_marks_empty_llm_timeout_as_parse_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return _fake_detail_inference(
            confidence=0.0,
            debug={"llm_detail_query_error": "Request timed out."},
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="Do you have any sterilization product?",
        nlu_data={"workflow": "catalog"},
        alias_map={},
        parser_rules=_db_rules(),
    )

    assert parsed.parse_failed is True
    assert parsed.parse_error == "Request timed out."
    assert parsed.attribute_filters == {}
    assert parsed.semantic_hints == []


@pytest.mark.asyncio
async def test_detail_query_parser_filter_only_query_is_not_detail_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return _fake_detail_inference(
            requested_fields=[],
            attribute_filters={"jewelry_type": "labret", "gauge": "14g", "material": "steel"},
            wants_image=False,
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="Give me a Labret with 14g with steel",
        nlu_data={"workflow": "catalog"},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )
    assert parsed.is_detail_request is False
    assert parsed.attribute_filters.get("jewelry_type") == "labret"
    assert parsed.attribute_filters.get("gauge") == "14g"
    assert parsed.attribute_filters.get("material") == "steel"


@pytest.mark.asyncio
async def test_detail_query_parser_extracts_extended_attribute_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return _fake_detail_inference(
            requested_fields=["attributes"],
            attribute_filters={
                "finish": "sterilized",
                "design": "heart",
                "jewelry_type": "ring",
                "outer_diameter": "8mm",
                "ring_size": "7",
                "opal_color": "blue",
            },
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="Show sterilized heart ring with 8mm outer diameter and ring size 7 in blue opal color",
        nlu_data={"workflow": "catalog"},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )

    assert parsed.attribute_filters.get("finish") == "sterilized"
    assert parsed.attribute_filters.get("design") == "heart"
    assert parsed.attribute_filters.get("jewelry_type") == "ring"
    assert parsed.attribute_filters.get("outer_diameter") == "8mm"
    assert parsed.attribute_filters.get("ring_size") == "7"
    assert parsed.attribute_filters.get("opal_color") == "blue"


@pytest.mark.asyncio
async def test_detail_query_parser_async_uses_llm_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return SimpleNamespace(
            requested_fields=["price", "image", "bogus"],
            attribute_filters={"color": "  Opal ", "gauge": "25 gauge"},
            wants_image=True,
            semantic_hints=["heart"],
            clarify_focus="",
            confidence=0.91,
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="Show me details",
        nlu_data={"workflow": "catalog"},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )

    assert parsed.requested_fields == ["price", "image"]
    assert parsed.attribute_filters.get("color") == "opal"
    assert parsed.attribute_filters.get("gauge") == "25 gauge"
    assert parsed.wants_image is True
    assert parsed.semantic_hints == ["heart"]
    assert parsed.is_detail_request is True


@pytest.mark.asyncio
async def test_detail_query_parser_async_clarifies_low_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_infer_detail_query(**kwargs):
        return SimpleNamespace(
            requested_fields=["price"],
            attribute_filters={"color": "opal"},
            wants_image=True,
            semantic_hints=["sterilization"],
            clarify_focus="",
            confidence=0.1,
        )

    monkeypatch.setattr(
        "app.services.chat.parsing.detail_query_parser.infer_detail_query",
        fake_infer_detail_query,
    )

    parsed = await DetailQueryParser.parse_async(
        user_text="I want something",
        nlu_data={"workflow": "catalog"},
        alias_map=_db_alias_map(),
        parser_rules=_db_rules(),
    )

    assert parsed.requested_fields == []
    assert parsed.attribute_filters == {}
    assert parsed.wants_image is False
    assert parsed.semantic_hints == []
    assert parsed.clarify_focus == "detail_request_needs_specific_product"
    assert parsed.is_detail_request is False


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
    assert payload.reply_text == "I found 1 matching product."
    assert "Master code:" not in payload.reply_text
    assert "Image:" not in payload.reply_text
    assert payload.card_policy_reason == "single_match_text_only"
    assert len(payload.product_carousel) == 1
    assert payload.carousel_msg == "Example Product has 1 option. Open it to view details."
    assert payload.follow_up_questions == []


def test_detail_response_builder_includes_product_code_when_requested() -> None:
    match = _card(
        sku="DMBJ38",
        name="DMBJ38",
        attributes={"master_code": "DMBJ38", "material": "Steel", "jewelry_type": "Labret"},
    )
    payload = DetailResponseBuilder.build_detail_reply(
        matches=[match],
        requested_fields=["sku", "attributes"],
        attribute_filters={},
        missing_fields_by_product={},
        wants_image=False,
        max_matches=3,
    )

    assert "Product code: DMBJ38" in payload.reply_text
    assert "Key details:" in payload.reply_text


def test_product_detail_resolver_treats_master_code_as_exact_product_anchor() -> None:
    first = _card(
        sku="BLK466-F02A12",
        name="BLK466",
        attributes={"master_code": "BLK466", "material": "Gold"},
    )
    second = _card(
        sku="BLK466-F04A12",
        name="BLK466",
        attributes={"master_code": "BLK466", "material": "Gold"},
    )
    resolver = ProductDetailResolver()
    resolved = resolver.resolve_detail_request(
        candidate_cards=[first, second],
        distance_by_id={str(first.id): 0.0, str(second.id): 0.0},
        requested_fields=["price"],
        attribute_filters={},
        sku_token="BLK466",
        nlu_product_code="BLK466",
        max_matches=3,
        min_confidence=0.55,
    )

    assert resolved.has_exact_match is True
    assert [item.sku for item in resolved.matches] == ["BLK466-F02A12", "BLK466-F04A12"]


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
    assert payload.carousel_msg == "BLK466 has 2 options. Open it to view details."
    assert payload.product_carousel
    assert payload.reply_text.startswith("I found 2 options for BLK466.")
    assert "Key details:" in payload.reply_text
    assert "[JEWELRY TYPE] Barbell" in payload.reply_text
    assert "Attributes:" not in payload.reply_text
    assert "Top master code:" not in payload.reply_text
    assert payload.follow_up_questions == []


def test_detail_response_builder_stock_summary_uses_entire_variant_set() -> None:
    first = _card(
        sku="BRUBN2-F04000",
        name="BRUBN2",
        stock_status="in_stock",
        in_stock=True,
        attributes={"master_code": "BRUBN2"},
    )
    second = _card(
        sku="BRUBN2-F06000",
        name="BRUBN2",
        stock_status="out_of_stock",
        in_stock=False,
        attributes={"master_code": "BRUBN2"},
    )
    payload = DetailResponseBuilder.build_detail_reply(
        matches=[first, second],
        requested_fields=["stock"],
        attribute_filters={},
        missing_fields_by_product={},
        wants_image=False,
        max_matches=3,
    )

    assert payload.reply_text.startswith("I found 2 options for BRUBN2.")
    assert "Stock: mixed availability" in payload.reply_text


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
    assert payload.reply_text.startswith("I found 2 options for BLK466.")
    assert "Key details:" in payload.reply_text
    assert "[MATERIAL] Gold" in payload.reply_text
    assert "[COLOR] Gold" in payload.reply_text
    assert "Attributes:" not in payload.reply_text
    assert "Top master code:" not in payload.reply_text
    assert payload.carousel_msg == "BLK466 has 2 options. Open it to view details."


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

    assert payload.reply_text == "I found images for 2 options in BLK466."
    assert "SKU:" not in payload.reply_text
    assert payload.card_policy_reason == "image_master_grouped"
    assert len(payload.product_carousel) == 1
