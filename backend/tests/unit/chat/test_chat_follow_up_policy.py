from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")

from app.schemas.chat import ProductCard
from app.services.chat.retrieval import follow_up_policy
from app.services.chat.service import ChatService

STOPWORDS = {"show", "for", "the", "and", "with", "you", "me", "what"}
PRODUCT_TERMS = {"product", "products", "labret", "barbell", "ring", "material", "gauge", "color"}
POLICY_TERMS = {"shipping", "return", "refund", "warranty"}


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
        stopwords=STOPWORDS,
        product_terms=PRODUCT_TERMS,
        policy_terms=POLICY_TERMS,
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
        stopwords=STOPWORDS,
        product_terms=PRODUCT_TERMS,
        limit=4,
    )
    assert questions
    assert any("Show more Labret options" == q for q in questions) or any("Show products in Titanium" == q for q in questions)


def test_chat_service_filter_follow_up_questions_wrapper_compatible() -> None:
    service = ChatService(db=object())
    kept = service._filter_follow_up_questions(
        questions=["Show labret options", "What is your shipping policy?"],
        user_text="Need labret",
        route="browse_products",
        has_products=True,
        retrieval_gate={"use_products": True, "use_knowledge": False},
    )
    assert "Show labret options" in kept


def test_build_product_follow_up_questions_skips_see_more_when_quick_reply_disabled() -> None:
    products = [
        _card(sku="A-1", attrs={"material": "Gold", "color": "Gold"}),
    ]
    questions = follow_up_policy.build_product_follow_up_questions(
        products=products,
        attribute_filters={"color": "gold", "material": "gold"},
        user_text="I am looking for Gold product",
        stopwords=STOPWORDS,
        product_terms=PRODUCT_TERMS,
        has_more_results=True,
        limit=4,
    )

    assert questions
    assert not any(str(item).lower().startswith("see more") for item in questions)
