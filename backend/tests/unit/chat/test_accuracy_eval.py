from __future__ import annotations

from app.services.chat.observability import accuracy_eval
from app.services.chat.observability import regression_eval


def test_accuracy_eval_default_dataset_paths_match_supported_suites() -> None:
    all_paths = accuracy_eval.default_dataset_paths(suite="all")
    routing_paths = accuracy_eval.default_dataset_paths(suite="routing")
    parser_paths = accuracy_eval.default_dataset_paths(suite="parser")
    response_paths = accuracy_eval.default_dataset_paths(suite="response")
    long_context_paths = accuracy_eval.default_dataset_paths(suite="long_context")
    adversarial_paths = accuracy_eval.default_dataset_paths(suite="adversarial")

    assert len(all_paths) == 5
    assert len(routing_paths) == 1
    assert len(parser_paths) == 1
    assert len(response_paths) == 1
    assert len(long_context_paths) == 1
    assert len(adversarial_paths) == 1
    assert routing_paths[0].name == "chat_routing_cases.json"
    assert parser_paths[0].name == "chat_parser_cases.json"
    assert response_paths[0].name == "chat_response_contract_cases.json"
    assert long_context_paths[0].name == "chat_long_context_cases.json"
    assert adversarial_paths[0].name == "chat_adversarial_cases.json"


def test_accuracy_eval_load_accuracy_cases_filters_by_suite() -> None:
    routing_cases = accuracy_eval.load_accuracy_cases(suite="routing")
    parser_cases = accuracy_eval.load_accuracy_cases(suite="parser")
    response_cases = accuracy_eval.load_accuracy_cases(suite="response")
    long_context_cases = accuracy_eval.load_accuracy_cases(suite="long_context")
    adversarial_cases = accuracy_eval.load_accuracy_cases(suite="adversarial")

    assert routing_cases
    assert parser_cases
    assert response_cases
    assert long_context_cases
    assert adversarial_cases
    assert {case["suite"] for case in routing_cases} == {"routing"}
    assert {case["suite"] for case in parser_cases} == {"parser"}
    assert {case["suite"] for case in response_cases} == {"response"}
    assert {case["suite"] for case in long_context_cases} == {"long_context"}
    assert {case["suite"] for case in adversarial_cases} == {"adversarial"}


def test_accuracy_eval_response_cases_include_capture_inputs() -> None:
    response_cases = accuracy_eval.load_accuracy_cases(suite="response")

    assert response_cases
    for case in response_cases:
        inputs = dict(case.get("inputs") or {})
        assert str(inputs.get("message") or "").strip()


def test_regression_eval_default_cases_exclude_response_contract_cases() -> None:
    cases = regression_eval.load_regression_cases()

    assert cases
    assert all(case["kind"] != "response_contract" for case in cases)
    assert {case["suite"] for case in cases} == {"routing", "parser"}


def test_regression_eval_routing_case_uses_live_understanding_and_decision_path() -> None:
    case = {
        "id": "routing-live-catalog",
        "suite": "routing",
        "bucket": "browse",
        "kind": "routing_decision",
        "inputs": {
            "text": "Show me titanium labrets",
            "channel": "widget",
            "locale": "en-US",
            "sku_tokens": [],
        },
        "expected": {
            "workflow": "catalog",
            "execution_mode": "agentic",
            "internal_workflow": "catalog_search",
            "workflow_hypothesis": "catalog_search",
            "understanding_source": "llm",
            "selection_source": "agentic",
        },
    }

    result = regression_eval.evaluate_case(case)

    assert result["passed"] is True


def test_regression_eval_routing_case_supports_understanding_llm_fixtures() -> None:
    case = {
        "id": "routing-live-llm",
        "suite": "routing",
        "bucket": "off_topic",
        "kind": "routing_decision",
        "inputs": {
            "text": "I need help with something on the site.",
            "channel": "widget",
            "locale": "en-US",
            "sku_tokens": [],
        },
        "understanding_llm_responses": [
            {
                "workflow_hypothesis": "off_topic",
                "needs_products": False,
                "needs_knowledge": False,
                "store_overview_request": False,
                "knowledge_query": "",
                "reason": "unrelated_non_store_request",
                "confidence": 0.94,
            }
        ],
        "expected": {
            "workflow": "off_topic",
            "execution_mode": "component",
            "internal_workflow": "off_topic",
            "workflow_hypothesis": "off_topic",
            "understanding_source": "llm",
            "llm_call_count": 1,
        },
    }

    result = regression_eval.evaluate_case(case)

    assert result["passed"] is True


def test_accuracy_eval_uses_pre_normalized_actual_results_without_losing_workflow() -> None:
    case = {
        "id": "normalized-actual",
        "suite": "response",
        "bucket": "product_contract",
        "kind": "response_contract",
        "expected": {
            "workflow": "catalog",
            "reply_must_include": ["gold"],
            "product_count_min": 1,
        },
    }
    actual_results = {
        "normalized-actual": {
            "workflow": "catalog",
            "reply_text": "Found a gold option for you.",
            "follow_up_questions": [],
            "sources": [],
            "product_carousel": [{"sku": "SKU-1"}],
            "debug": {},
        }
    }

    result = accuracy_eval.evaluate_case(case, actual_results=actual_results)

    assert result["passed"] is True


def test_accuracy_eval_contract_supports_legacy_actual_response_fixture_key() -> None:
    case = {
        "id": "legacy-actual-response",
        "suite": "adversarial",
        "bucket": "prompt_injection",
        "kind": "adversarial_contract",
        "actual_response": {
            "workflow": "off_topic",
            "reply_text": "I can't help with that request.",
            "follow_up_questions": [],
            "sources": [],
            "product_carousel": [],
            "components": [],
            "debug": {},
        },
        "expected": {
            "workflow": "off_topic",
            "reply_must_include": ["can't help"],
            "product_count_max": 0,
            "source_count_max": 0,
        },
    }

    result = accuracy_eval.evaluate_case(case)

    assert result["passed"] is True
    assert result["kind"] == "adversarial_contract"


def test_accuracy_eval_missing_contract_actual_preserves_case_kind() -> None:
    case = {
        "id": "missing-long-context-actual",
        "suite": "long_context",
        "bucket": "anchor_retention",
        "kind": "long_context_contract",
        "expected": {
            "workflow": "catalog",
        },
    }

    result = accuracy_eval.evaluate_case(case)

    assert result["passed"] is False
    assert result["kind"] == "long_context_contract"
    assert result["mismatches"] == ["actual response missing"]


def test_accuracy_eval_response_contract_supports_component_and_source_shape_checks() -> None:
    case = {
        "id": "response-shape-check",
        "suite": "response",
        "bucket": "failure_contract",
        "kind": "response_contract",
        "expected": {
            "workflow": "fallback",
            "required_component_types": ["clarify", "quick_replies"],
            "forbidden_component_types": ["product_cards", "error"],
            "source_titles_include_any": ["Shipping Policy"],
            "reply_must_include": ["clarify"],
            "product_count_max": 0,
        },
    }
    actual_results = {
        "response-shape-check": {
            "routing": {"workflow": "fallback"},
            "components": [
                {
                    "type": "clarify",
                    "data": {"message": "Could you clarify what shipping details you need?"},
                },
                {
                    "type": "quick_replies",
                    "data": {"items": ["Shipping methods", "International shipping"]},
                },
            ],
            "sources": [{"title": "Shipping Policy"}],
            "product_carousel": [],
            "debug": {},
        }
    }

    result = accuracy_eval.evaluate_case(case, actual_results=actual_results)

    assert result["passed"] is True


def test_accuracy_eval_response_contract_supports_exact_groundedness_checks() -> None:
    case = {
        "id": "response-groundedness-check",
        "suite": "response",
        "bucket": "policy_contract",
        "kind": "response_contract",
        "expected": {
            "workflow": "knowledge",
            "component_types_exact": ["assistant_message", "quick_replies"],
            "source_titles_exact": ["Shipping Policy"],
            "source_snippets_include_all": ["destination", "service level"],
            "top_product_skus_exact": [],
        },
    }
    actual_results = {
        "response-groundedness-check": {
            "routing": {"workflow": "knowledge"},
            "components": [
                {
                    "type": "assistant_message",
                    "data": {"text": "Shipping depends on destination and service level."},
                },
                {
                    "type": "quick_replies",
                    "data": {"items": ["Do you ship internationally?"]},
                },
            ],
            "sources": [
                {
                    "title": "Shipping Policy",
                    "content_snippet": "Shipping depends on destination and service level.",
                }
            ],
            "product_carousel": [],
            "debug": {},
        }
    }

    result = accuracy_eval.evaluate_case(case, actual_results=actual_results)

    assert result["passed"] is True


def test_accuracy_eval_normalizes_follow_up_text_components_into_contract_follow_ups() -> None:
    case = {
        "id": "response-follow-up-text-normalization",
        "suite": "response",
        "bucket": "product_contract",
        "kind": "response_contract",
        "expected": {
            "workflow": "catalog",
            "follow_ups_include": ["Try gold pieces"],
            "component_types_exact": ["assistant_message", "quick_replies"],
        },
    }
    actual_results = {
        "response-follow-up-text-normalization": {
            "routing": {"workflow": "catalog"},
            "components": [
                {
                    "type": "assistant_message",
                    "data": {"text": "I found matching gold products."},
                },
                {
                    "type": "assistant_message",
                    "data": {
                        "text": "If you want, I can help you:\n- gold pieces",
                        "placement": "after_quick_replies",
                    },
                },
            ],
            "sources": [],
            "product_carousel": [],
            "debug": {},
        }
    }

    result = accuracy_eval.evaluate_case(case, actual_results=actual_results)

    assert result["passed"] is True


def test_accuracy_eval_quick_replies_extracts_labels_from_dict_items() -> None:
    case = {
        "id": "response-quick-reply-dict-items",
        "suite": "response",
        "bucket": "policy_contract",
        "kind": "response_contract",
        "expected": {
            "workflow": "knowledge",
            "follow_ups_include": ["Do you ship internationally?"],
            "component_types_exact": ["assistant_message", "quick_replies"],
        },
    }
    actual_results = {
        "response-quick-reply-dict-items": {
            "routing": {"workflow": "knowledge"},
            "components": [
                {
                    "type": "assistant_message",
                    "data": {"text": "Shipping depends on destination and service level."},
                },
                {
                    "type": "quick_replies",
                    "data": {
                        "items": [
                            {
                                "label": "Do you ship internationally?",
                                "action": "knowledge_follow_up",
                            }
                        ]
                    },
                },
            ],
            "sources": [],
            "product_carousel": [],
            "debug": {},
        }
    }

    result = accuracy_eval.evaluate_case(case, actual_results=actual_results)

    assert result["passed"] is True


def test_accuracy_eval_response_contract_supports_context_anchor_checks() -> None:
    case = {
        "id": "response-context-check",
        "suite": "response",
        "bucket": "context_contract",
        "kind": "context_contract",
        "expected": {
            "workflow": "catalog",
            "context": {
                "anchor_type": "mixed",
                "product_skus_exact": ["EVAL-GOLD-LAB-1"],
                "source_titles_exact": ["Eval Returns Policy"],
            },
            "product_count_min": 1,
            "source_count_min": 1,
        },
    }
    actual_results = {
        "response-context-check": {
            "routing": {"workflow": "catalog"},
            "reply_text": "The gold labret is out of stock, and unopened jewelry can be returned within 30 days.",
            "follow_up_questions": [],
            "sources": [
                {
                    "title": "Eval Returns Policy",
                    "content_snippet": "Unopened jewelry can be returned within 30 days.",
                }
            ],
            "product_carousel": [
                {
                    "sku": "EVAL-GOLD-LAB-1",
                }
            ],
            "components": [
                {
                    "type": "assistant_message",
                    "data": {
                        "text": "The gold labret is out of stock, and unopened jewelry can be returned within 30 days.",
                    },
                }
            ],
            "debug": {},
        }
    }

    result = accuracy_eval.evaluate_case(case, actual_results=actual_results)

    assert result["passed"] is True


def test_accuracy_eval_response_contract_flags_wrong_context_anchor() -> None:
    case = {
        "id": "response-context-wrong-anchor",
        "suite": "response",
        "bucket": "context_contract",
        "kind": "context_contract",
        "expected": {
            "workflow": "catalog",
            "context": {
                "anchor_type": "product",
                "primary_product_sku": "EVAL-GOLD-LAB-1",
                "product_skus_exact": ["EVAL-GOLD-LAB-1"],
            },
        },
    }
    actual_results = {
        "response-context-wrong-anchor": {
            "routing": {"workflow": "catalog"},
            "reply_text": "The titanium labret is in stock.",
            "follow_up_questions": [],
            "sources": [],
            "product_carousel": [
                {
                    "sku": "EVAL-TI-LAB-1",
                }
            ],
            "components": [
                {
                    "type": "assistant_message",
                    "data": {
                        "text": "The titanium labret is in stock.",
                    },
                }
            ],
            "debug": {},
        }
    }

    result = accuracy_eval.evaluate_case(case, actual_results=actual_results)

    assert result["passed"] is False
    assert any("context.primary_product_sku" in mismatch for mismatch in result["mismatches"])


def test_accuracy_eval_response_contract_supports_no_anchor_context() -> None:
    case = {
        "id": "response-context-no-anchor",
        "suite": "response",
        "bucket": "context_contract",
        "kind": "context_contract",
        "expected": {
            "workflow": "fallback",
            "context": {
                "anchor_type": "none",
            },
            "product_count_max": 0,
            "source_count_max": 0,
        },
    }
    actual_results = {
        "response-context-no-anchor": {
            "routing": {"workflow": "fallback"},
            "reply_text": "Could you clarify which product or policy you mean?",
            "follow_up_questions": ["Could you clarify which product or policy you mean?"],
            "sources": [],
            "product_carousel": [],
            "components": [
                {
                    "type": "clarify",
                    "data": {
                        "message": "Could you clarify which product or policy you mean?",
                    },
                }
            ],
            "debug": {},
        }
    }

    result = accuracy_eval.evaluate_case(case, actual_results=actual_results)

    assert result["passed"] is True


def test_accuracy_eval_long_context_and_adversarial_group_summary() -> None:
    cases = [
        {
            "id": "long-context-summary",
            "suite": "long_context",
            "bucket": "anchor_retention",
            "kind": "long_context_contract",
            "turns": [
                {"role": "user", "content": "Show me titanium labrets."},
                {"role": "assistant", "content": "I found titanium labrets."},
                {"role": "user", "content": "What about the gold one?"},
            ],
            "expected": {
                "workflow": "catalog",
                "reply_must_include": ["gold", "out of stock"],
                "context": {
                    "anchor_type": "product",
                    "primary_product_sku": "EVAL-GOLD-LAB-1",
                    "product_skus_exact": ["EVAL-GOLD-LAB-1"],
                },
                "turn_count_min": 3,
            },
        },
        {
            "id": "adversarial-summary",
            "suite": "adversarial",
            "bucket": "prompt_injection",
            "kind": "adversarial_contract",
            "expected": {
                "workflow": "off_topic",
                "reply_must_include": ["can't help", "products"],
                "reply_must_not_include": ["system prompt"],
                "context": {
                    "anchor_type": "none",
                },
                "source_count_max": 0,
                "product_count_max": 0,
            },
        },
    ]
    actual_results = {
        "long-context-summary": {
            "routing": {"workflow": "catalog"},
            "reply_text": "The gold labret variant EVAL-GOLD-LAB-1 is out of stock.",
            "follow_up_questions": [],
            "sources": [],
            "product_carousel": [{"sku": "EVAL-GOLD-LAB-1"}],
            "components": [{"type": "assistant_message", "data": {"text": "The gold labret variant EVAL-GOLD-LAB-1 is out of stock."}}],
            "debug": {},
        },
        "adversarial-summary": {
            "routing": {"workflow": "off_topic"},
            "reply_text": "I can't help with that. I can help with products and store policies.",
            "follow_up_questions": [],
            "sources": [],
            "product_carousel": [],
            "components": [{"type": "assistant_message", "data": {"text": "I can't help with that. I can help with products and store policies."}}],
            "debug": {},
        },
    }

    summary = accuracy_eval.run_accuracy_suite(cases, actual_results=actual_results)

    assert summary["failed"] == 0
    assert summary["by_focus_group"] == {"adversarial": 1, "long_context": 1}
    assert summary["trend_summary"]["by_focus_group"] == {"adversarial": 1, "long_context": 1}


def test_accuracy_eval_failure_summary_clusters_repeatable_mismatches() -> None:
    cases = [
        {
            "id": "long-context-failure",
            "suite": "long_context",
            "bucket": "anchor_retention",
            "kind": "long_context_contract",
            "expected": {
                "workflow": "catalog",
            },
        },
        {
            "id": "adversarial-failure",
            "suite": "adversarial",
            "bucket": "prompt_injection",
            "kind": "adversarial_contract",
            "expected": {
                "workflow": "catalog",
            },
        },
        {
            "id": "adversarial-pass",
            "suite": "adversarial",
            "bucket": "safe_refusal",
            "kind": "adversarial_contract",
            "expected": {
                "workflow": "off_topic",
            },
        },
    ]
    actual_results = {
        "long-context-failure": {
            "routing": {"workflow": "fallback"},
            "reply_text": "Unable to help.",
            "follow_up_questions": [],
            "sources": [],
            "product_carousel": [],
            "components": [],
            "debug": {},
        },
        "adversarial-failure": {
            "routing": {"workflow": "fallback"},
            "reply_text": "Unable to help.",
            "follow_up_questions": [],
            "sources": [],
            "product_carousel": [],
            "components": [],
            "debug": {},
        },
        "adversarial-pass": {
            "routing": {"workflow": "off_topic"},
            "reply_text": "I can't help with that.",
            "follow_up_questions": [],
            "sources": [],
            "product_carousel": [],
            "components": [],
            "debug": {},
        },
    }

    summary = accuracy_eval.run_accuracy_suite(cases, actual_results=actual_results)

    assert summary["total"] == 3
    assert summary["failed"] == 2
    assert summary["failure_summary"]["total"] == 2
    assert summary["failure_summary"]["by_kind"] == {
        "adversarial_contract": 1,
        "long_context_contract": 1,
    }
    assert summary["failure_summary"]["by_suite"] == {
        "adversarial": 1,
        "long_context": 1,
    }
    assert summary["failure_summary"]["top_mismatch_signatures"][0]["signature"] == (
        "workflow: expected 'catalog', got 'fallback'"
    )
    assert summary["failure_summary"]["top_mismatch_signatures"][0]["count"] == 2
