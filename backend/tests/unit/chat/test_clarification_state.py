from __future__ import annotations

from app.services.chat.runtime import clarification_state


def test_clarification_state_tracks_repeated_task_count() -> None:
    task_id = clarification_state.build_task_id(
        intent="product_detail",
        missing_slots=["product_anchor"],
        semantic_query="how much is this",
        hard_constraints={},
    )

    state = clarification_state.record_clarification(
        {},
        task_id=task_id,
        reason="pending_task_missing_slot",
        missing_slots=["product_anchor"],
    )
    state = clarification_state.record_clarification(
        state,
        task_id=task_id,
        reason="pending_task_missing_slot",
        missing_slots=["product_anchor"],
    )

    assert state["clarification_count"] == 2
    assert clarification_state.should_stop_clarifying(state, task_id=task_id) is True


def test_clarification_state_marks_answer_merged() -> None:
    task_id = clarification_state.build_task_id(
        intent="product_detail",
        missing_slots=["product_anchor"],
        semantic_query="how much is this",
        hard_constraints={},
    )
    state = clarification_state.record_clarification(
        {},
        task_id=task_id,
        reason="pending_task_missing_slot",
        missing_slots=["product_anchor"],
    )

    merged = clarification_state.record_answer_merged(state, user_answer="the black titanium one")

    assert merged["previous_user_answer"] == "the black titanium one"
    assert merged["merged_into_search_plan"] is True


def test_clarification_state_tracks_context_metadata() -> None:
    state = clarification_state.record_clarification(
        {},
        task_id="clarify:test",
        reason="context_needs_clarification",
        missing_slots=["product_anchor"],
        context_type="detail_reference",
        missing_slot="product_anchor",
    )

    assert state["last_context_type"] == "detail_reference"
    assert state["last_missing_slot"] == "product_anchor"
    assert state["answered_missing_slot"] is False
