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


def test_classify_failure_uses_harness_trace_when_metrics_are_sparse() -> None:
    result = qa_failure_analysis.classify_failure(
        user_text="I mean a labret that comes pre-sterilized",
        response=_response(
            reply_text="I couldn't find an exact match, so here are close alternatives.",
            workflow="fallback",
            debug={
                "harness_trace": {
                    "route": "catalog",
                    "workflow": "catalog_search",
                    "execution_mode": "component",
                    "retrieved_products": 1,
                    "grounding_status": "unrelated",
                    "fallback_used": True,
                    "fallback_reason": "agentic_empty",
                    "clarification_required": True,
                    "clarification_reason": "missing_product_anchor",
                }
            },
        ),
        chat_metrics={},
    )

    assert result.bucket == "hard_constraint_no_match"
    assert "harness_route=catalog" in result.signals
    assert "harness_workflow=catalog_search" in result.signals
    assert "harness_fallback_used" in result.signals
    assert "harness_fallback_reason=agentic_empty" in result.signals
    assert "harness_clarification_required" in result.signals
    assert "harness_clarification_reason=missing_product_anchor" in result.signals


def test_classify_failure_detects_agentic_expected_tool_missing() -> None:
    result = qa_failure_analysis.classify_failure(
        user_text="what is your return policy?",
        response=_response(reply_text="Could you clarify shipping scope?", workflow="knowledge"),
        chat_metrics={
            "workflow": "knowledge",
            "status": "fallback",
            "agentic_expected_tool_missing": True,
            "agentic_fallback_reason": "agentic_expected_tool_missing",
        },
    )

    assert result.bucket == "agentic_expected_tool_missing"
    assert result.severity == "medium"
    assert "agentic_expected_tool_missing" in result.signals


def test_classify_failure_detects_agentic_grounding_failed() -> None:
    result = qa_failure_analysis.classify_failure(
        user_text="show me titanium labrets",
        response=_response(reply_text="I found products.", workflow="catalog"),
        chat_metrics={
            "workflow": "catalog",
            "status": "fallback",
            "agentic_grounding_failed": True,
            "agentic_fallback_reason": "agentic_grounding_failed",
        },
    )

    assert result.bucket == "agentic_grounding_failed"
    assert result.severity == "medium"
    assert "agentic_grounding_failed" in result.signals
