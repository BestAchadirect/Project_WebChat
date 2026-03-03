import pytest
from fastapi import HTTPException

from app.services.imports.klevu_sync_service import KlevuProductSyncService


def test_build_payload_matches_required_klevu_shape() -> None:
    service = KlevuProductSyncService()
    payload = service._build_payload(api_key="demo-key", limit=100, offset=200)

    assert payload["context"]["apiKeys"] == ["demo-key"]
    query = payload["recordQueries"][0]
    assert query["typeOfRequest"] == "SEARCH"
    assert query["settings"]["query"]["term"] == "*"
    assert query["settings"]["typeOfRecords"] == ["KLEVU_PRODUCT"]
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
    # Master code is derived from the simple-product suffix when explicit master code is absent.
    assert payload["master_code"] == "DIND19"
