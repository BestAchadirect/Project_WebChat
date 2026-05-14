from types import SimpleNamespace

from app.services.chat.observability.regression_case_templates import (
    build_regression_review_bundle,
    build_review_bundle_from_qa_log,
)


def test_build_regression_review_bundle_marks_review_required_and_keeps_traceability() -> None:
    bundle = build_regression_review_bundle(
        qa_log_id="fa5c01c0-daf8-4b42-8944-2f469cb4809e",
        question="Do you have sterilization with opal body jewelry?",
        answer="Do you mean whether our store offers sterilization services for opal body jewelry?",
        status="success",
        sources=[],
        chat_metrics={
            "conversation_id": 1305,
            "workflow": "knowledge",
            "route": "component_primary",
            "grounding_status": "needs_clarification",
            "grounding_safe_action": "clarify",
            "failure_bucket": "mixed_intent_clarification",
            "failure_reason": "product and policy terms were both present",
            "failure_suggested_action": "Split the request into product and policy parts.",
            "source_count": 0,
            "product_count": 0,
        },
    )

    assert bundle["conversation_id"] == 1305
    assert bundle["observed"]["failure_bucket"] == "mixed_intent_clarification"
    assert bundle["coverage_case_template"]["review_required"] is True
    assert bundle["coverage_case_template"]["expected_workflow"] == "__REVIEW_REQUIRED__"
    assert bundle["coverage_case_template"]["meta"]["qa_log_id"] == "fa5c01c0-daf8-4b42-8944-2f469cb4809e"
    assert bundle["recommended_targets"][0]["dataset"].endswith("chat_customer_message_coverage_cases.json")
    assert bundle["response_contract_template"]["review_required"] is True
    assert bundle["response_contract_template"]["fallback_actual_response"]["debug"]["conversation_id"] == 1305


def test_build_regression_review_bundle_recommends_response_contract_for_grounding_failures() -> None:
    bundle = build_regression_review_bundle(
        qa_log_id="seed-log",
        question="I mean opal body jewelry that comes pre-sterilized",
        answer="I couldn't find an exact match, so here are close alternatives.",
        status="success",
        sources=[{"title": "Products"}],
        chat_metrics={
            "workflow": "catalog",
            "grounding_status": "unrelated",
            "failure_analysis": {
                "bucket": "hard_constraint_no_match",
                "reason": "the request carried hard constraints that the catalog could not satisfy exactly",
                "suggested_action": "Keep the hard constraint intact.",
                "confidence": 0.95,
                "severity": "high",
                "signals": ["hard_constraint_signal"],
            },
            "source_count": 1,
            "product_count": 1,
        },
    )

    target_paths = [item["dataset"] for item in bundle["recommended_targets"]]
    assert any(path.endswith("chat_customer_message_coverage_cases.json") for path in target_paths)
    assert any(path.endswith("chat_response_contract_cases.json") for path in target_paths)
    assert bundle["response_contract_template"]["bucket"] == "hard_constraint_no_match"
    assert bundle["response_contract_template"]["fallback_actual_response"]["sources"][0]["title"] == "Products"


def test_build_review_bundle_from_qa_log_reads_chat_metrics_from_token_usage() -> None:
    qa_log = SimpleNamespace(
        id="bundle-log",
        question="Do you have more of this? what similar to GLBO product?",
        answer="Here is the same item again.",
        status="success",
        sources=[],
        token_usage={
            "chat_metrics": {
                "conversation_id": 1305,
                "workflow": "catalog",
                "grounding_status": "unrelated",
                "failure_bucket": "related_product_anchor_reuse",
                "failure_reason": "a related-product follow-up reused the current anchor instead of excluding it",
                "failure_suggested_action": "Use the current product as the seed, but exclude the anchor/master code from the similar-product results.",
            }
        },
    )

    bundle = build_review_bundle_from_qa_log(qa_log)

    assert bundle["qa_log_id"] == "bundle-log"
    assert bundle["conversation_id"] == 1305
    assert bundle["observed"]["failure_bucket"] == "related_product_anchor_reuse"
    assert bundle["coverage_case_template"]["meta"]["observed_workflow"] == "catalog"
