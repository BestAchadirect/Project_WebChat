from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.imports

from app.models.klevu_sync import KlevuSyncRun, KlevuSyncRunStatus
from app.services.imports.klevu.service import KlevuProductSyncService
from tests.fixtures.klevu import FakeActiveRunsDB, FakeSingleRunDB


@pytest.mark.asyncio
async def test_ensure_no_active_run_recovers_stale_orphan_running_run() -> None:
    service = KlevuProductSyncService()
    now = datetime.now(timezone.utc)
    run = KlevuSyncRun(
        id=UUID("00000000-0000-0000-0000-0000000000A1"),
        status=KlevuSyncRunStatus.running,
        started_at=now - timedelta(hours=2),
        updated_at=now - timedelta(minutes=90),
        cancel_requested=True,
    )
    db = FakeActiveRunsDB([run])

    await service._ensure_no_active_run(db)

    assert run.status == KlevuSyncRunStatus.stopped
    assert run.cancel_requested is False
    assert run.completed_at is not None
    assert db.commit_calls == 1


def test_pending_run_not_treated_as_stale_in_external_worker_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = KlevuProductSyncService()
    now = datetime.now(timezone.utc)
    run = KlevuSyncRun(
        id=UUID("00000000-0000-0000-0000-0000000000B3"),
        status=KlevuSyncRunStatus.pending,
        started_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=2),
    )
    monkeypatch.setattr(service, "_use_external_worker", lambda: True)
    assert service._is_stale_active_run(run) is False


@pytest.mark.asyncio
async def test_ensure_no_active_run_keeps_live_running_run_blocking() -> None:
    service = KlevuProductSyncService()
    now = datetime.now(timezone.utc)
    run = KlevuSyncRun(
        id=UUID("00000000-0000-0000-0000-0000000000A2"),
        status=KlevuSyncRunStatus.running,
        started_at=now - timedelta(minutes=1),
        updated_at=now - timedelta(seconds=10),
    )
    db = FakeActiveRunsDB([run])

    with pytest.raises(HTTPException) as exc_info:
        await service._ensure_no_active_run(db)

    assert exc_info.value.status_code == 409
    assert run.status == KlevuSyncRunStatus.running
    assert db.commit_calls == 0


@pytest.mark.asyncio
async def test_request_full_sync_cancel_recovers_stale_orphan_running_run() -> None:
    service = KlevuProductSyncService()
    now = datetime.now(timezone.utc)
    run = KlevuSyncRun(
        id=UUID("00000000-0000-0000-0000-0000000000A3"),
        status=KlevuSyncRunStatus.running,
        started_at=now - timedelta(hours=2),
        updated_at=now - timedelta(minutes=45),
        cancel_requested=True,
    )
    db = FakeSingleRunDB(run)

    payload = await service.request_full_sync_cancel(db, run_id=run.id)

    assert payload["updated"] is True
    assert payload["run"]["status"] == "cancelled"
    assert run.status == KlevuSyncRunStatus.cancelled
    assert run.cancel_requested is False
    assert run.completed_at is not None
    assert db.commit_calls == 1
