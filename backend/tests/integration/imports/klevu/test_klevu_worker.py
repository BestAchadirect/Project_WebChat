from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

pytestmark = pytest.mark.imports

from app.models.klevu_sync import KlevuSyncRun, KlevuSyncRunStatus
from app.services.imports.klevu.service import KlevuProductSyncService
from tests.fixtures.klevu import FakeQueueCreateDB, FakeSingleRunDB


@pytest.mark.asyncio
async def test_start_full_sync_queues_when_external_worker_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = KlevuProductSyncService()
    db = FakeQueueCreateDB()

    async def fake_ensure_no_active_run(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(service, "_ensure_no_active_run", fake_ensure_no_active_run)
    monkeypatch.setattr(service, "_use_external_worker", lambda: True)

    payload = await service.start_full_sync(
        db,
        page_size=100,
        max_pages=None,
        requests_per_minute=180,
        stop_after_pages=None,
    )

    assert payload["run"]["status"] == "pending"
    assert db.commit_calls == 1
    assert service._background_tasks == {}


@pytest.mark.asyncio
async def test_resume_full_sync_queues_when_external_worker_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = KlevuProductSyncService()
    now = datetime.now(timezone.utc)
    run = KlevuSyncRun(
        id=UUID("00000000-0000-0000-0000-0000000000B2"),
        status=KlevuSyncRunStatus.cancelled,
        page_size=100,
        max_pages=None,
        current_offset=1200,
        last_success_offset=1100,
        started_at=now - timedelta(hours=1),
        completed_at=now - timedelta(minutes=5),
        updated_at=now - timedelta(minutes=5),
    )
    db = FakeSingleRunDB(run)

    async def fake_ensure_no_active_run(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(service, "_ensure_no_active_run", fake_ensure_no_active_run)
    monkeypatch.setattr(service, "_use_external_worker", lambda: True)

    payload = await service.resume_full_sync(db, run_id=run.id)

    assert payload["run"]["status"] == "pending"
    assert run.status == KlevuSyncRunStatus.pending
    assert service._background_tasks == {}
    assert db.commit_calls >= 1


@pytest.mark.asyncio
async def test_worker_once_returns_idle_when_no_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = KlevuProductSyncService()

    async def fake_process():
        return {"claimed": False}

    monkeypatch.setattr(service, "process_next_queued_full_sync_run", fake_process)
    result = await service.run_queued_full_sync_worker(once=True, poll_seconds=0.25)
    assert result["status"] == "idle"
    assert result["processed"] == 0


@pytest.mark.asyncio
async def test_worker_once_returns_processed_when_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = KlevuProductSyncService()

    async def fake_process():
        return {"claimed": True, "run_id": "run-1"}

    monkeypatch.setattr(service, "process_next_queued_full_sync_run", fake_process)
    result = await service.run_queued_full_sync_worker(once=True, poll_seconds=0.25)
    assert result["status"] == "processed"
    assert result["processed"] == 1
    assert result["run_id"] == "run-1"
