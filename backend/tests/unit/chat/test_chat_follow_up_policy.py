from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")

from app.schemas.chat import ProductCard
from app.services.chat.presentation import clarify_policy
from app.services.chat.retrieval import follow_up_policy
from app.services.chat.presentation import follow_up_builder
from app.services.chat.service import ChatService

STOPWORDS = {"show", "for", "the", "and", "with", "you", "me", "what"}


def _card(*, sku: str, attrs: dict) -> ProductCard:
    return ProductCard(
        id=uuid4(),
        object_id=sku,
        sku=sku,
        legacy_sku=[],
        name=sku,
        price=10.0,
        currency="USD",
        stock_status="in_stock",
        image_url=None,
        product_url=None,
        attributes=attrs,
    )


def test_filter_follow_up_questions_keeps_relevant_product_questions() -> None:
    kept = follow_up_policy.filter_follow_up_questions(
        questions=[
            "Show labret options in steel",
            "What is your return policy?",
            "Show labret options in steel",
        ],
        user_text="Need steel labret",
        route="browse_products",
        has_products=True,
        retrieval_gate={"use_products": True, "use_knowledge": False},
        limit=5,
    )
    assert kept == ["Show labret options in steel"]


def test_build_product_follow_up_questions_without_context_uses_attributes() -> None:
    products = [
        _card(sku="A-1", attrs={"jewelry_type": "Labret", "material": "Titanium", "gauge": "16g"}),
        _card(sku="A-2", attrs={"jewelry_type": "Ring", "material": "Steel", "color": "Black"}),
    ]
    questions = follow_up_policy.build_product_follow_up_questions(
        products=products,
        attribute_filters={},
        user_text="show me products",
        limit=4,
    )
    assert questions
    assert any("Try Titanium pieces" == q for q in questions) or any("See Titanium Labret" == q for q in questions)


def test_filter_follow_up_questions_keeps_knowledge_prompts_for_policy_routes() -> None:
    kept = follow_up_policy.filter_follow_up_questions(
        questions=[
            "What is your shipping policy?",
            "How can I contact you?",
            "Show titanium jewelry",
        ],
        user_text="Need shipping info",
        route="knowledge",
        has_products=False,
        retrieval_gate={"use_products": False, "use_knowledge": True, "is_policy_like": True},
        limit=5,
    )
    assert kept == ["What is your shipping policy?", "How can I contact you?"]


def test_build_product_clarify_follow_ups_use_master_code() -> None:
    product = _card(sku="SKU-1", attrs={"master_code": "MC-1"})
    follow_ups = clarify_policy.build_product_clarify_follow_ups(
        products=[product],
        attribute_filters={},
        needs_knowledge=False,
        limit=3,
    )

    assert follow_ups == ["Show details for MC-1"]


def test_filter_follow_up_questions_collapses_near_duplicate_product_phrasing() -> None:
    kept = follow_up_policy.filter_follow_up_questions(
        questions=[
            "Show more titanium jewelry",
            "Try titanium pieces",
            "Show products in titanium",
            "See titanium options",
        ],
        user_text="Need titanium",
        route="catalog",
        has_products=True,
        retrieval_gate={"use_products": True, "use_knowledge": False},
        limit=5,
    )
    assert kept == ["Show more titanium jewelry"]


def test_chat_service_filter_follow_up_questions_wrapper_compatible() -> None:
    service = ChatService(db=object())
    kept = service._filter_follow_up_questions(
        questions=["Show labret options", "What is your shipping policy?"],
        user_text="Need labret",
        route="browse_products",
        has_products=True,
        retrieval_gate={"use_products": True, "use_knowledge": False},
    )
    assert kept == ["Show labret options"]


def test_build_product_follow_up_questions_skips_see_more_when_quick_reply_disabled() -> None:
    products = [
        _card(sku="A-1", attrs={"material": "Gold", "color": "Gold"}),
    ]
    questions = follow_up_policy.build_product_follow_up_questions(
        products=products,
        attribute_filters={"color": "gold", "material": "gold"},
        user_text="I am looking for Gold product",
        has_more_results=True,
        limit=4,
    )

    assert questions
    assert not any(str(item).lower().startswith("see more") for item in questions)


def test_build_product_follow_up_questions_uses_varied_refinement_phrases() -> None:
    products = [
        _card(sku="A-1", attrs={"jewelry_type": "Labret", "material": "Titanium", "gauge": "16g", "color": "Black", "threading": "Threadless"}),
        _card(sku="A-2", attrs={"jewelry_type": "Labret", "material": "Steel", "gauge": "18g", "color": "Gold", "threading": "Internally Threaded"}),
    ]

    questions = follow_up_policy.build_product_follow_up_questions(
        products=products,
        attribute_filters={"jewelry_type": "Labret"},
        user_text="show me labrets",
        limit=5,
    )

    assert any(q.startswith("See ") for q in questions)
    assert any(q.startswith("Focus on ") for q in questions)
    assert len({q.split(" ", 1)[0] for q in questions}) >= 2


def test_build_show_more_follow_up_suppresses_last_page_prompt() -> None:
    products = [
        _card(sku="A-1", attrs={"material": "Gold", "jewelry_type": "Labret"}),
        _card(sku="A-2", attrs={"material": "Gold", "jewelry_type": "Labret"}),
    ]

    follow_ups = follow_up_builder.build_show_more_follow_up(
        products=products,
        attribute_filters={"material": "Gold"},
        result_count=2,
        display_count=2,
        display_offset=0,
        pagination_has_more=False,
        display_attribute_value=lambda value: value.title(),
        top_product_attributes=lambda **kwargs: ["Gold"],
    )

    assert follow_ups == []


def test_build_conversion_follow_ups_suppresses_show_more_on_last_page() -> None:
    products = [
        _card(sku="A-1", attrs={"material": "Gold", "jewelry_type": "Labret"}),
        _card(sku="A-2", attrs={"material": "Gold", "jewelry_type": "Labret"}),
    ]
    debug_meta = {
        "catalog_query_cache_key": "chat:components:query_ids:gold",
        "catalog_query_product_ids": ["A-1", "A-2"],
        "catalog_pagination_has_more": False,
    }

    follow_ups = follow_up_builder.build_conversion_follow_ups(
        products=products,
        attribute_filters={"material": "Gold"},
        user_text="show me gold jewelry",
        needs_knowledge=False,
        result_count=2,
        display_count=2,
        display_offset=0,
        debug_meta=debug_meta,
        top_product_attributes=lambda **kwargs: ["Gold"],
        build_show_more_follow_up=lambda **kwargs: follow_up_builder.build_show_more_follow_up(
            display_attribute_value=lambda value: value.title(),
            top_product_attributes=lambda **inner_kwargs: ["Gold"],
            **kwargs,
        ),
        dedupe_follow_up_questions=lambda items, limit=5: list(items)[:limit],
    )

    assert not any(str(item).lower().startswith("show more") for item in follow_ups)
