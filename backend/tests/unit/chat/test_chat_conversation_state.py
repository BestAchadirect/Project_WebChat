from __future__ import annotations

from app.services.chat.runtime import conversation_state


def test_load_state_normalizes_and_preserves_unknown_keys() -> None:
    state = conversation_state.load_state(
        {
            "version": "2",
            "last_workflow": " catalog ",
            "last_attribute_filters": {"Material": " titanium ", "color": ""},
            "last_requested_fields": ["Price", "price", "", "stock"],
            "last_product_ids": ["123", "", "123", "456"],
            "last_currency": " usd ",
            "tone_recent": [
                {"key": " clarify:routing_fallback ", "style": "DIRECT", "variant_id": "2"},
                {"key": "", "style": "casual", "variant_id": 1},
            ],
            "extra_field": {"keep": True},
        }
    )

    assert state["version"] == 2
    assert state["last_workflow"] == "catalog"
    assert state["last_attribute_filters"] == {"material": "titanium"}
    assert state["last_requested_fields"] == ["price", "stock"]
    assert state["last_product_ids"] == ["123", "456"]
    assert state["last_currency"] == "USD"
    assert state["last_user_query"] == ""
    assert state["last_product_skus"] == []
    assert state["last_answer_source_ids"] == []
    assert state["last_inventory_claim"] == {"sku": "", "stock_status": "", "last_stock_sync_at": ""}
    assert state["active_product"] == {}
    assert state["displayed_products"] == []
    assert state["tone_recent"] == [{"key": "clarify:routing_fallback", "style": "direct", "variant_id": 2}]
    assert state["extra_field"] == {"keep": True}


def test_load_state_v1_payload_backfills_new_fields() -> None:
    state = conversation_state.load_state({"version": 1, "last_workflow": "knowledge"})

    assert state["version"] == 1
    assert state["last_workflow"] == "knowledge"
    assert state["last_user_query"] == ""
    assert state["last_product_skus"] == []
    assert state["last_answer_source_ids"] == []
    assert state["last_inventory_claim"] == {"sku": "", "stock_status": "", "last_stock_sync_at": ""}
    assert state["active_product"] == {}
    assert state["displayed_products"] == []

def test_apply_response_update_persists_clean_tone_recent() -> None:
    state = conversation_state.apply_response_update(
        {},
        requested_fields=["price"],
        currency="usd",
        route="catalog",
        tone_recent=[
            {"key": "catalog:default_reply", "style": "neutral", "variant_id": 1},
            {"key": "invalid", "style": "", "variant_id": -1},
        ],
    )

    assert state["tone_recent"] == [{"key": "catalog:default_reply", "style": "neutral", "variant_id": 1}]


def test_apply_updates_store_extended_context_fields() -> None:
    state = conversation_state.apply_retrieval_update(
        {},
        product_ids=["id-1"],
        product_skus=["sku-1", "SKU-1", "sku-2"],
        route="catalog",
    )
    state = conversation_state.apply_response_update(
        state,
        requested_fields=["stock"],
        currency="usd",
        route="catalog",
        query_product_ids=["query-1", "query-2"],
        answer_source_ids=["kb-1", "kb-1", "kb-2"],
        inventory_claim={"sku": "SKU-1", "stock_status": "IN_STOCK", "last_stock_sync_at": "2026-03-12T00:00:00Z"},
        active_product={
            "product_id": "id-1",
            "sku": "SKU-1",
            "master_code": "SKU-1",
            "name": "Titanium Labret",
            "source": "single_result",
            "confidence": 0.85,
            "created_at": "2026-03-12T00:00:00Z",
            "updated_at": "2026-03-12T00:00:00Z",
        },
        displayed_products=[
            {
                "position": 1,
                "product_id": "id-1",
                "sku": "SKU-1",
                "master_code": "SKU-1",
                "name": "Titanium Labret",
            }
        ],
    )

    assert state["last_product_skus"] == ["sku-1", "sku-2"]
    assert state["last_query_product_ids"] == ["query-1", "query-2"]
    assert state["last_answer_source_ids"] == ["kb-1", "kb-2"]
    assert state["last_inventory_claim"] == {
        "sku": "SKU-1",
        "stock_status": "in_stock",
        "last_stock_sync_at": "2026-03-12T00:00:00Z",
    }
    assert state["active_product"]["product_id"] == "id-1"
    assert state["active_product"]["source"] == "single_result"
    assert state["displayed_products"][0]["position"] == 1
    assert state["displayed_products"][0]["descriptors"] == {}


def test_displayed_products_from_cards_persists_descriptor_subset() -> None:
    card = type(
        "Card",
        (),
        {
            "id": "id-1",
            "product_id": "id-1",
            "sku": "SKU-1",
            "name": "Titanium Labret",
            "title": "Titanium Labret",
            "attributes": {
                "master_code": "SKU-1",
                "material": "titanium",
                "color": "black",
                "gauge": "16g",
                "length": "8mm",
                "threading": "internally threaded",
                "jewelry_type": "labret",
                "ignored": "value",
            },
        },
    )()

    displayed = conversation_state.displayed_products_from_cards([card])

    assert displayed[0]["descriptors"] == {
        "material": "titanium",
        "color": "black",
        "gauge": "16g",
        "length": "8mm",
        "threading": "internally threaded",
        "jewelry_type": "labret",
    }


def test_split_state_round_trips_memory_and_continuation_fields() -> None:
    raw_state = {
        "version": 3,
        "last_workflow": "catalog",
        "last_refined_query": "refined query",
        "last_user_query": "original query",
        "last_product_ids": ["id-1"],
        "last_product_skus": ["sku-1"],
        "tone_recent": [{"key": "catalog:default_reply", "style": "neutral", "variant_id": 1}],
        "last_query_cache_key": "query-cache-key",
        "last_query_product_ids": [f"query-{idx}" for idx in range(1, 13)],
        "last_result_count": 2,
        "last_display_offset": 4,
        "last_display_limit": 8,
        "extra": {"keep": True},
    }

    memory, continuation = conversation_state.split_state(raw_state)

    assert memory.last_workflow == "catalog"
    assert memory.last_product_ids == ["id-1"]
    assert memory.tone_recent == [{"key": "catalog:default_reply", "style": "neutral", "variant_id": 1}]
    assert continuation.last_query_cache_key == "query-cache-key"
    assert continuation.last_query_product_ids == [f"query-{idx}" for idx in range(1, 13)]
    assert continuation.last_display_offset == 4
    assert continuation.last_display_limit == 8

    round_tripped = conversation_state.build_state_payload(memory=memory, continuation=continuation)

    assert round_tripped["version"] == 3
    assert round_tripped["last_workflow"] == "catalog"
    assert round_tripped["last_query_cache_key"] == "query-cache-key"
    assert round_tripped["last_query_product_ids"] == [f"query-{idx}" for idx in range(1, 13)]
    assert round_tripped["last_display_offset"] == 4
    assert round_tripped["last_display_limit"] == 8
