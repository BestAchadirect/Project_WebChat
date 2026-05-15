from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.chat.runtime import context_policy, context_resolver, conversation_state


def _state(**overrides):
    base = conversation_state.load_state(
        {
            "version": conversation_state.CONVERSATION_STATE_VERSION,
            "last_attribute_filters": {
                "material": "titanium",
                "jewelry_type": "labret",
            },
            "last_query_cache_key": "cache-key",
            "last_query_product_ids": ["p1", "p2", "p3"],
            "last_display_offset": 0,
            "last_display_limit": 10,
            "last_result_count": 30,
            "last_product_ids": ["p1", "p2"],
            "displayed_products": [
                {
                    "position": 1,
                    "product_id": "p1",
                    "sku": "A1",
                    "master_code": "A1",
                    "name": "Titanium Labret",
                    "descriptors": {
                        "material": "titanium",
                        "color": "black",
                        "gauge": "16g",
                        "jewelry_type": "labret",
                    },
                },
                {
                    "position": 2,
                    "product_id": "p2",
                    "sku": "B2",
                    "master_code": "B2",
                    "name": "Steel Labret",
                    "descriptors": {
                        "material": "steel",
                        "color": "silver",
                        "gauge": "14g",
                        "jewelry_type": "labret",
                    },
                },
            ],
            "updated_at": context_policy.utc_timestamp(),
        }
    )
    base.update(overrides)
    return conversation_state.load_state(base)


def test_context_resolver_reuses_product_type_for_material_refinement() -> None:
    result = context_resolver.resolve_context(
        user_message="What about gold?",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_action == "update"
    assert result.context_used is True
    assert result.resolved_filters == {"material": "gold", "jewelry_type": "labret"}
    assert result.confidence == 0.8


def test_context_resolver_ignores_inferred_type_for_material_refinement() -> None:
    result = context_resolver.resolve_context(
        user_message="What about gold?",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={"material": "gold", "jewelry_type": "Bio Labrets With Real Gold"},
    )

    assert result.context_action == "update"
    assert result.reset_reason is None
    assert result.resolved_filters == {"material": "gold", "jewelry_type": "labret"}


def test_context_resolver_adds_length_refinement_to_prior_filters() -> None:
    result = context_resolver.resolve_context(
        user_message="with 8mm length",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_action == "update"
    assert result.resolved_filters == {
        "material": "titanium",
        "jewelry_type": "labret",
        "length": "8mm",
    }


def test_context_resolver_replaces_negated_material() -> None:
    result = context_resolver.resolve_context(
        user_message="not titanium, steel",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.resolved_filters["material"] == "steel"
    assert result.resolved_filters["jewelry_type"] == "labret"


def test_context_resolver_resets_on_new_product_type() -> None:
    result = context_resolver.resolve_context(
        user_message="Now show nose rings",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_action == "reset"
    assert result.reset_reason in {"explicit_topic_switch", "new_product_type"}
    assert result.context_used is False
    assert result.resolved_filters == {"jewelry_type": "nose ring"}


def test_context_resolver_handles_pagination_from_previous_state() -> None:
    result = context_resolver.resolve_context(
        user_message="show more",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.resolved_intent == "pagination"
    assert result.context_action == "reuse"
    assert result.context_used is True
    assert result.pagination_action == {
        "query_cache_key": "cache-key",
        "query_product_ids": ["p1", "p2", "p3"],
        "display_offset": 0,
        "display_limit": 10,
        "result_count": 30,
        "state_offset": 0,
    }


def test_context_resolver_uses_active_product_for_sensitive_followup() -> None:
    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    result = context_resolver.resolve_context(
        user_message="Is it in stock?",
        conversation_id=1,
        loaded_state=_state(
            active_product={
                "product_id": "p2",
                "sku": "B2",
                "master_code": "B2",
                "name": "Steel Labret",
                "source": "position_reference",
                "confidence": 0.9,
                "created_at": context_policy.utc_timestamp(now),
                "updated_at": context_policy.utc_timestamp(now),
            }
        ),
        workflow="catalog",
        extracted_filters={},
        now=now,
    )

    assert result.context_action == "reuse"
    assert result.resolved_intent == "inventory_check"
    assert result.active_product["product_id"] == "p2"
    assert result.confidence == 0.85


def test_context_resolver_clarifies_vague_product_reference_with_multiple_products() -> None:
    result = context_resolver.resolve_context(
        user_message="Is it in stock?",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_action == "clarify"
    assert result.context_used is False
    assert result.confidence == 0.4
    assert result.clarification_reason == "product_anchor_ambiguous"


def test_context_resolver_maps_position_reference_to_displayed_product() -> None:
    result = context_resolver.resolve_context(
        user_message="Tell me about the second one",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_action == "reuse"
    assert result.active_product["product_id"] == "p2"
    assert result.active_product["source"] == "position_reference"
    assert result.confidence == 0.9


def test_context_resolver_resolves_explicit_sku() -> None:
    result = context_resolver.resolve_context(
        user_message="Can I see DMBJ38?",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_action == "reset"
    assert result.active_product["sku"] == "DMBJ38"
    assert result.active_product["source"] == "explicit_sku"
    assert result.confidence == 0.95


def test_context_resolver_resumes_pending_product_anchor_task() -> None:
    result = context_resolver.resolve_context(
        user_message="The steel one",
        conversation_id=1,
        loaded_state=_state(
            pending_task={
                "task_type": "product_stock_question",
                "missing_slot": "product_anchor",
                "original_question": "Is it in stock?",
                "turns_remaining": 2,
                "created_at": context_policy.utc_timestamp(),
            }
        ),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.resolved_intent == "clarification_response"
    assert result.context_type == "pending_task_resume"
    assert result.pending_task_action == {"action": "resume", "clear": True}
    assert result.active_product["product_id"] == "p2"


def test_context_resolver_does_not_use_expired_active_product() -> None:
    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    old = now - timedelta(minutes=25)
    result = context_resolver.resolve_context(
        user_message="Is it available?",
        conversation_id=1,
        loaded_state=_state(
            active_product={
                "product_id": "p1",
                "sku": "A1",
                "master_code": "A1",
                "name": "Titanium Labret",
                "source": "single_result",
                "confidence": 0.85,
                "created_at": context_policy.utc_timestamp(old),
                "updated_at": context_policy.utc_timestamp(old),
            }
        ),
        workflow="catalog",
        extracted_filters={},
        now=now,
    )

    assert result.context_action == "clarify"
    assert result.context_used is False
    assert result.confidence == 0.4


def test_context_resolver_merges_strict_filter_refinement() -> None:
    result = context_resolver.resolve_context(
        user_message="Only black titanium",
        conversation_id=1,
        loaded_state=_state(
            last_attribute_filters={"jewelry_type": "nose ring"},
            displayed_products=[],
            last_product_ids=[],
        ),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_type == "filter_refinement"
    assert result.context_used is True
    assert result.safe_to_retrieve is True
    assert result.merged_attribute_filters == {
        "jewelry_type": "nose ring",
        "color": "black",
        "material": "titanium",
    }


def test_context_resolver_resolves_product_index_detail_reference() -> None:
    result = context_resolver.resolve_context(
        user_message="How much is the first one?",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
        requested_fields=["price"],
        is_detail_request=True,
    )

    assert result.context_type == "detail_reference"
    assert result.safe_to_retrieve is True
    assert result.should_clarify is False
    assert result.resolved_product_anchor_ids == ["p1"]
    assert result.selected_product_index == 0


def test_context_resolver_allows_filtered_detail_request_without_prior_anchor() -> None:
    result = context_resolver.resolve_context(
        user_message="price and stock for black barbell 25mm",
        conversation_id=1,
        loaded_state=_state(
            last_attribute_filters={},
            displayed_products=[],
            last_product_ids=[],
            last_product_skus=[],
            active_product={},
        ),
        workflow="catalog",
        extracted_filters={"jewelry_type": "barbell", "color": "black", "gauge": "25mm"},
        requested_fields=["price", "stock"],
        is_detail_request=True,
    )

    assert result.context_type == "detail_reference"
    assert result.context_action == "update"
    assert result.safe_to_retrieve is True
    assert result.should_clarify is False
    assert result.resolved_intent == "inventory_check"
    assert result.resolved_filters == {"jewelry_type": "barbell", "color": "black", "gauge": "25mm"}


def test_context_resolver_resumes_pending_task_from_master_code() -> None:
    result = context_resolver.resolve_context(
        user_message="DMBJ38",
        conversation_id=1,
        loaded_state=_state(
            pending_task={
                "task_type": "product_details_question",
                "missing_slot": "product_anchor",
                "original_question": "Which product do you mean?",
                "turns_remaining": 2,
                "created_at": context_policy.utc_timestamp(),
            }
        ),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_type == "pending_task_resume"
    assert result.resume_pending_task is True
    assert result.resolved_product_anchor_skus == ["DMBJ38"]
    assert result.safe_to_retrieve is True


def test_context_resolver_uses_previous_products_for_price_comparison() -> None:
    result = context_resolver.resolve_context(
        user_message="Which one is cheaper?",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_type == "price_compare"
    assert result.context_used is True
    assert result.safe_to_retrieve is True
    assert result.resolved_product_anchor_ids == ["p1", "p2"]


def test_context_resolver_uses_previous_products_for_related_products() -> None:
    result = context_resolver.resolve_context(
        user_message="Show me similar products",
        conversation_id=1,
        loaded_state=_state(),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_type == "related_products"
    assert result.context_used is True
    assert result.safe_to_retrieve is True
    assert result.resolved_product_anchor_ids == ["p1", "p2"]


def test_context_resolver_clarifies_stale_pagination_request() -> None:
    result = context_resolver.resolve_context(
        user_message="Show more",
        conversation_id=1,
        loaded_state=_state(last_display_offset=20, last_result_count=30),
        workflow="catalog",
        extracted_filters={},
        client_action="catalog_pagination",
        client_action_payload={"display_offset": 10, "display_limit": 10, "query_cache_key": "cache-key"},
    )

    assert result.context_type == "pagination"
    assert result.should_clarify is True
    assert result.clarification_reason == "pagination_stale"
    assert result.safe_to_retrieve is False


def test_context_resolver_resolves_compare_by_index() -> None:
    result = context_resolver.resolve_context(
        user_message="Compare the first and third one",
        conversation_id=1,
        loaded_state=_state(
            last_product_ids=["p1", "p2", "p3"],
            displayed_products=[
                {
                    "position": 1,
                    "product_id": "p1",
                    "sku": "A1",
                    "master_code": "A1",
                    "name": "Titanium Labret",
                },
                {
                    "position": 2,
                    "product_id": "p2",
                    "sku": "B2",
                    "master_code": "B2",
                    "name": "Steel Labret",
                },
                {
                    "position": 3,
                    "product_id": "p3",
                    "sku": "C3",
                    "master_code": "C3",
                    "name": "Gold Labret",
                },
            ],
        ),
        workflow="catalog",
        extracted_filters={},
    )

    assert result.context_type == "compare_reference"
    assert result.safe_to_retrieve is True
    assert result.resolved_product_anchor_ids == ["p1", "p3"]
    assert result.selected_product_indices == [0, 2]
