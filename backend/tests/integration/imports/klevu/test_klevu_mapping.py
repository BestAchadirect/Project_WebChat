from __future__ import annotations

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.imports

from app.services.imports.klevu.service import KlevuProductSyncService


def test_build_payload_matches_required_klevu_shape() -> None:
    service = KlevuProductSyncService()
    payload = service._build_payload(api_key="demo-key", limit=100, offset=200)

    assert payload["context"]["apiKeys"] == ["demo-key"]
    query = payload["recordQueries"][0]
    assert query["typeOfRequest"] == "SEARCH"
    assert query["settings"]["query"]["term"] == "*"
    assert query["settings"]["typeOfRecords"] == ["KLEVU_PRODUCT"]
    assert query["settings"]["searchPrefs"] == ["disableGrouping"]
    assert query["settings"]["sortOrder"] == "updatedAt:desc"
    assert query["settings"]["limit"] == 100
    assert query["settings"]["offset"] == 200


def test_payload_size_guard_raises_when_payload_exceeds_limit() -> None:
    service = KlevuProductSyncService()
    payload = service._build_payload(api_key="demo-key", limit=100, offset=0)

    with pytest.raises(HTTPException) as exc_info:
        service._ensure_payload_size(payload, max_bytes=10)

    assert exc_info.value.status_code == 400
    assert "payload too large" in str(exc_info.value.detail).lower()


def test_extract_records_supports_record_queries_shape() -> None:
    service = KlevuProductSyncService()
    response = {
        "recordQueries": [
            {
                "id": "q1",
                "records": [{"sku": "A1"}, {"sku": "A2"}],
            }
        ]
    }
    records = service._extract_records(response)
    assert [record["sku"] for record in records] == ["A1", "A2"]


def test_extract_records_supports_query_results_shape() -> None:
    service = KlevuProductSyncService()
    response = {
        "queryResults": [
            {
                "id": "q1",
                "records": [{"sku": "B1"}],
            }
        ]
    }
    records = service._extract_records(response)
    assert [record["sku"] for record in records] == ["B1"]


def test_record_mapping_returns_none_without_sku_like_fields() -> None:
    service = KlevuProductSyncService()
    assert service._record_to_payload({"name": "No SKU Product"}) is None


def test_record_mapping_normalizes_compound_sku_and_attributes() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "SEND;;;;SEND-D62P64",
            "name": "High polish endless nose ring",
            "shortDesc": "Short description from Klevu.",
            "price": "0.55",
            "inStock": "yes",
            "material": "316l",
            "klevu_category": "KLEVU_PRODUCT;;Nose Piercing;;Surgical Steel;;@ku@kuCategory@ku@",
        }
    )
    assert payload is not None
    assert payload["raw_sku"] == "SEND;;;;SEND-D62P64"
    assert payload["sku"] == "SEND-D62P64"
    assert payload["master_code"] == "SEND"
    assert payload["description"] == "Short description from Klevu."
    assert payload["price"] == 0.55
    assert payload["stock_status"] == "in_stock"
    assert payload["attributes"]["material"] == "Steel"
    assert payload["attributes"]["category"] == "Nose Piercing;;Surgical Steel"
    assert payload["attributes"]["source_raw_sku"] == "SEND;;;;SEND-D62P64"


def test_record_mapping_keeps_missing_optional_fields_as_none() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload({"sku": "ABC;;;;ABC-01", "inStock": "yes"})
    assert payload is not None
    assert payload["price"] is None
    assert payload["visibility"] is None
    assert payload["is_featured"] is None
    assert payload["priority"] is None


def test_record_mapping_stores_klevu_id_separate_from_object_id() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "MAP;;;;MAP-01",
            "id": "klevu-123",
            "objectId": "magento-777",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["klevu_id"] == "klevu-123"
    assert payload["object_id"] == "magento-777"


def test_record_mapping_uses_klevu_id_when_object_id_is_missing() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "MAP2;;;;MAP2-01",
            "id": "klevu-789",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["klevu_id"] == "klevu-789"
    assert payload["object_id"] is None


def test_record_mapping_moves_simple_parent_object_id_to_klevu_id() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "HEXVD9-000000",
            "objectId": "77567",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["klevu_id"] == "77567"
    assert payload["object_id"] is None


def test_record_mapping_keeps_non_simple_object_id_when_klevu_id_missing() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "HEXVD9;;;;HEXVD9-F13000",
            "objectId": "77567",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["klevu_id"] is None
    assert payload["object_id"] == "77567"


def test_record_mapping_normalizes_simple_parent_duplicate_ids() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "USUD13I-000000",
            "id": "247485-247482",
            "objectId": "247485-247482",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["klevu_id"] == "247485-247482"
    assert payload["object_id"] is None


def test_record_mapping_does_not_add_compound_raw_sku_to_legacy() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "ERK652;;;;ERK652-B01000",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["legacy_sku"] == []


def test_record_mapping_filters_compound_legacy_tokens() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "LEG;;;;LEG-01",
            "legacy_sku": "LEG;;;;LEG-01,OLD-001|OLD-002",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["legacy_sku"] == ["OLD-001", "OLD-002"]


def test_record_mapping_normalizes_thumbnail_to_base_image_url() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "IMG;;;;IMG-01",
            "image": "https://www.achadirect.com/media/product/wholesale1_t/demo.jpg",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["image_url"] == "https://www.achadirect.com/media/product/wholesale1_b/demo.jpg"


def test_record_mapping_prefers_explicit_base_image_over_thumbnail() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "IMG2;;;;IMG2-01",
            "base_image": "https://www.achadirect.com/media/product/wholesale1_b/base.jpg",
            "image": "https://www.achadirect.com/media/product/wholesale1_t/thumb.jpg",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["image_url"] == "https://www.achadirect.com/media/product/wholesale1_b/base.jpg"


def test_simple_sku_000000_kept_in_sku_field() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "DIND19-000000",
            "name": "Display with simple SKU",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["sku"] == "DIND19-000000"
    assert payload["master_code"] == "DIND19"


def test_record_mapping_uses_shortdesc_only_for_description() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "DESC;;;;DESC-01",
            "description": "Legacy description should not be used",
            "shortDescription": "Legacy shortDescription should not be used",
            "shortDesc": "Canonical shortDesc value",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["description"] == "Canonical shortDesc value"


def test_record_mapping_without_shortdesc_keeps_description_none() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "DESC2;;;;DESC2-01",
            "description": "Should be ignored when shortDesc is absent",
            "shortDescription": "Should be ignored when shortDesc is absent",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["description"] is None


def test_category_normalization_uses_category_field_and_canonical_tokens() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "CAT;;;;CAT-01",
            "shortDesc": "Category normalization check",
            "category": "Silicon;;Ear Piercing others;;silicon;;Others",
            "inStock": "yes",
        }
    )
    assert payload is not None
    assert payload["attributes"]["category"] == "Silicone;;Ear Piercing Others;;Others"


def test_record_mapping_supports_camel_case_extended_attributes() -> None:
    service = KlevuProductSyncService()
    payload = service._record_to_payload(
        {
            "sku": "ATTR;;;;ATTR-01",
            "shortDesc": "Extended attribute mapping",
            "inStock": "yes",
            "opalColor": "Blue",
            "pearlColor": "White",
            "ringSize": "7",
            "outerDiameter": "8mm",
            "packingOption": "Box",
            "sizeInPack": "12",
            "quantityInBulk": "144",
        }
    )

    assert payload is not None
    assert payload["attributes"]["opal_color"] == "Blue"
    assert payload["attributes"]["pearl_color"] == "White"
    assert payload["attributes"]["ring_size"] == "7"
    assert payload["attributes"]["outer_diameter"] == "8mm"
    assert payload["attributes"]["packing_option"] == "Box"
    assert payload["attributes"]["size_in_pack"] == "12"
    assert payload["attributes"]["quantity_in_bulk"] == "144"


def test_klevu_category_normalization_splits_single_semicolon_segments() -> None:
    service = KlevuProductSyncService()
    normalized = service._normalize_klevu_category(
        "KLEVU_PRODUCT;;Belly Piercing;;Surgical Steel;Belly Banana;Loose;;@ku@kuCategory@ku@"
    )
    assert normalized == "Belly Piercing;;Surgical Steel;;Belly Banana;;Loose"


def test_run_config_snapshot_is_standardized() -> None:
    service = KlevuProductSyncService()
    snapshot = service._build_run_config_snapshot(
        page_size=100,
        max_pages=None,
        requests_per_minute=None,
        stop_after_pages=None,
    )

    assert set(snapshot.keys()) == {
        "page_size",
        "max_pages",
        "requests_per_minute",
        "stop_after_pages",
        "payload_max_bytes",
        "disable_grouping",
        "bulk_eav_enabled",
        "row_savepoint_enabled",
        "commit_every_pages",
        "cancel_check_every_pages",
        "defer_search_text",
    }
    assert snapshot["page_size"] == 100
    assert snapshot["max_pages"] is None
    assert snapshot["stop_after_pages"] is None
    assert isinstance(snapshot["requests_per_minute"], int)
    assert isinstance(snapshot["payload_max_bytes"], int)
    assert isinstance(snapshot["commit_every_pages"], int)
    assert isinstance(snapshot["cancel_check_every_pages"], int)


def test_run_config_snapshot_applies_runtime_overrides() -> None:
    service = KlevuProductSyncService()
    snapshot = service._build_run_config_snapshot(
        page_size=50,
        max_pages=900,
        requests_per_minute=150,
        stop_after_pages=20,
    )

    assert snapshot["page_size"] == 50
    assert snapshot["max_pages"] == 900
    assert snapshot["requests_per_minute"] == 150
    assert snapshot["stop_after_pages"] == 20
