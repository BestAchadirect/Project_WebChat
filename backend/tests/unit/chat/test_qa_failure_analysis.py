from types import SimpleNamespace

from app.services.chat.observability import qa_failure_analysis


def _response(*, reply_text: str, workflow: str = "catalog", debug: dict | None = None) -> SimpleNamespace:
    payload = {
        "reply_text": reply_text,
        "debug": dict(debug or {}),
        "routing": SimpleNamespace(workflow=workflow),
        "sources": [],
    }
    return SimpleNamespace(**payload)


def test_classify_failure_detects_mixed_intent_clarification() -> None:
    result = qa_failure_analysis.classify_failure(
        user_text="Do you have sterilization with opal body jewelry?",
        response=_response(
            reply_text="Could you clarify whether you want a product or a sterilization service?",
            workflow="knowledge",
        ),
        chat_metrics={"workflow": "knowledge", "status": "fallback"},
    )

    assert result.bucket == "mixed_intent_clarification"
    assert result.confidence >= 0.9


def test_classify_failure_detects_hard_constraint_no_match() -> None:
    result = qa_failure_analysis.classify_failure(
        user_text="I mean opal body jewelry that comes pre-sterilized",
        response=_response(
            reply_text="I couldn't find an exact match, so here are close alternatives.",
            workflow="catalog",
        ),
        chat_metrics={
            "workflow": "catalog",
            "status": "success",
            "grounding_status": "unrelated",
            "grounding_safe_action": "show_alternatives",
            "product_count": 1,
            "has_products": True,
        },
    )

    assert result.bucket == "hard_constraint_no_match"
    assert result.severity == "high"


def test_classify_failure_detects_related_product_anchor_reuse() -> None:
    result = qa_failure_analysis.classify_failure(
        user_text="Do you have more of this? what similar to GLBO product?",
        response=_response(
            reply_text="Here is the same item again.",
            workflow="catalog",
            debug={"context_related_product_followup_used": True},
        ),
        chat_metrics={
            "workflow": "catalog",
            "status": "success",
            "grounding_status": "unrelated",
            "grounding_safe_action": "show_alternatives",
            "product_count": 1,
            "has_products": True,
        },
    )

    assert result.bucket == "related_product_anchor_reuse"
    assert "related_followup_signal" in result.signals
