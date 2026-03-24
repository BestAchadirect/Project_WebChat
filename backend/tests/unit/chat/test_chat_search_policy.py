from __future__ import annotations

from app.services.chat.parsing.search_policy import (
    ALLOWED_PRODUCT_FILTERS,
    detect_attribute_list_target,
    normalize_filter_map,
    split_hard_and_soft_filters,
)


def test_detect_attribute_list_target_maps_list_queries() -> None:
    assert detect_attribute_list_target("What materials do you have?") == "material"
    assert detect_attribute_list_target("Show gauges") == "gauge"
    assert detect_attribute_list_target("Tell me more about the store") == ""


def test_split_hard_and_soft_filters_uses_shared_policy_keys() -> None:
    hard_filters, soft_filters = split_hard_and_soft_filters(
        attribute_filters={
            "gauge": "14g",
            "material": "titanium",
            "color": "opal",
            "source_raw_sku": "ABC-123",
        }
    )

    assert hard_filters == {
        "gauge": "14g",
    }
    assert soft_filters == {
        "material": "titanium",
        "color": "opal",
        "source_raw_sku": "ABC-123",
    }


def test_allowed_product_filters_remain_stable() -> None:
    assert {"material", "jewelry_type", "color"}.issubset(ALLOWED_PRODUCT_FILTERS)


def test_normalize_filter_map_applies_aliases_and_allowlist() -> None:
    normalized = normalize_filter_map(
        {
            "Type": "Labret",
            "diameter": "8mm",
            "ignored": "x",
            "color": "  Opal  ",
        },
        allowed_keys=ALLOWED_PRODUCT_FILTERS | {"outer_diameter"},
        key_aliases={"type": "jewelry_type", "diameter": "outer_diameter"},
    )

    assert normalized == {
        "jewelry_type": "Labret",
        "outer_diameter": "8mm",
        "color": "Opal",
    }
