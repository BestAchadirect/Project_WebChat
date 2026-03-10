from __future__ import annotations

from uuid import UUID

import pytest

pytestmark = pytest.mark.imports

from app.services.imports.klevu.service import (
    KlevuProductSyncService,
    KlevuSyncStats,
    PageLookupContext,
)
from tests.fixtures.klevu import ProcessRowsDB


def test_object_id_upsert_prefers_explicit_object_id() -> None:
    service = KlevuProductSyncService()
    resolved = service._resolve_object_id_for_upsert(
        current_object_id="legacy-object-id",
        incoming_object_id="magento-777",
        incoming_klevu_id="klevu-123",
    )
    assert resolved == "magento-777"


def test_object_id_upsert_clears_legacy_klevu_fallback_value() -> None:
    service = KlevuProductSyncService()
    resolved = service._resolve_object_id_for_upsert(
        current_object_id="150847-245783",
        incoming_object_id=None,
        incoming_klevu_id="150847-245783",
    )
    assert resolved is None


def test_object_id_upsert_keeps_existing_non_klevu_object_id_when_source_missing() -> None:
    service = KlevuProductSyncService()
    resolved = service._resolve_object_id_for_upsert(
        current_object_id="magento-12345",
        incoming_object_id=None,
        incoming_klevu_id="klevu-123",
    )
    assert resolved == "magento-12345"


@pytest.mark.asyncio
async def test_process_page_rows_counts_unchanged_as_skipped_and_not_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = KlevuProductSyncService()
    stats = KlevuSyncStats()
    unchanged_id = UUID("00000000-0000-0000-0000-000000000001")

    monkeypatch.setattr(
        service,
        "_record_to_payload",
        lambda _record: {"sku": "SKU-001", "master_code": "SKU"},
    )

    async def fake_lookup_context(*_args, **_kwargs) -> PageLookupContext:
        return PageLookupContext(
            products_by_sku={},
            products_by_object_id={},
            products_by_klevu_id={},
        )

    async def fake_preload_groups(*_args, **_kwargs) -> None:
        return None

    async def fake_upsert_payload(*_args, **_kwargs) -> tuple[str, UUID]:
        return "unchanged", unchanged_id

    monkeypatch.setattr(service, "_build_page_lookup_context", fake_lookup_context)
    monkeypatch.setattr(service, "_preload_groups", fake_preload_groups)
    monkeypatch.setattr(service, "_upsert_payload", fake_upsert_payload)

    touched_ids = await service._process_page_rows(
        ProcessRowsDB(),
        records=[{"sku": "SKU-001"}],
        stats=stats,
        group_cache={},
        run_id=None,
        page_offset=0,
    )

    assert touched_ids == []
    assert stats.created == 0
    assert stats.updated == 0
    assert stats.skipped == 1
    assert stats.failed == 0
