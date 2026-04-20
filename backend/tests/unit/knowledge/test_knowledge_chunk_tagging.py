from __future__ import annotations

from app.services.knowledge.tagging import build_knowledge_chunk_tags, build_knowledge_query_tags


def test_build_knowledge_chunk_tags_detects_contact_support_terms() -> None:
    tags = build_knowledge_chunk_tags(
        article_title="How can I contact Acha?",
        article_category="Contact",
        chunk_text="You can contact us by email or phone to speak with a sales person.",
    )

    assert tags == ["contact"]


def test_build_knowledge_chunk_tags_detects_shipping_and_payment_terms() -> None:
    tags = build_knowledge_chunk_tags(
        article_title="Shipping and Payment",
        article_category="Policy",
        chunk_text="We ship by courier and accept bank transfer or card payment.",
    )

    assert tags == ["shipping", "payment"]


def test_build_knowledge_chunk_tags_detects_returns_and_refund_terms() -> None:
    tags = build_knowledge_chunk_tags(
        article_title="Return Policy",
        article_category="Refunds",
        chunk_text="Eligible returns can receive a refund or exchange.",
    )

    assert tags == ["refund", "returns"]


def test_build_knowledge_query_tags_reuses_chunk_rules() -> None:
    tags = build_knowledge_query_tags("I want to talk to a sales representative about shipping")

    assert tags == ["contact", "shipping"]


def test_build_knowledge_query_tags_supports_sale_person_typo() -> None:
    tags = build_knowledge_query_tags("I want to talk to a sale person")

    assert tags == ["contact"]


def test_build_knowledge_query_tags_detects_store_overview_location_terms() -> None:
    tags = build_knowledge_query_tags("Where is your showroom location and what are your hours?")

    assert tags == ["contact", "store_overview"]
