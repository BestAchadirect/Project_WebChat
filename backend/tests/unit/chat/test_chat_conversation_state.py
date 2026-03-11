from __future__ import annotations

from app.services.chat import conversation_state


def test_load_state_normalizes_and_preserves_unknown_keys() -> None:
    state = conversation_state.load_state(
        {
            "version": "2",
            "last_workflow": " catalog ",
            "last_attribute_filters": {"Material": " titanium ", "color": ""},
            "last_requested_fields": ["Price", "price", "", "stock"],
            "last_product_ids": ["123", "", "123", "456"],
            "last_currency": " usd ",
            "extra_field": {"keep": True},
        }
    )

    assert state["version"] == 2
    assert state["last_workflow"] == "catalog"
    assert state["last_attribute_filters"] == {"material": "titanium"}
    assert state["last_requested_fields"] == ["price", "stock"]
    assert state["last_product_ids"] == ["123", "456"]
    assert state["last_currency"] == "USD"
    assert state["extra_field"] == {"keep": True}


def test_follow_up_filter_merge_only_applies_to_short_referential_queries() -> None:
    assert conversation_state.should_merge_follow_up_filters(
        user_text="cheaper ones",
        current_filters={},
        sku_token=None,
    ) is True
    assert conversation_state.merge_filters({}, {"material": "titanium"}) == {"material": "titanium"}
    assert conversation_state.should_merge_follow_up_filters(
        user_text="show black ones",
        current_filters={"color": "black"},
        sku_token=None,
    ) is False
