from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.klevu_sync import KlevuSyncFailure, KlevuSyncRun, KlevuSyncRunStatus
from app.utils.pagination import normalize_pagination

from .types import KlevuSyncStats

logger = get_logger(__name__)


class KlevuRunControlMixin:
    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _resolved_rpm(requests_per_minute: int | None) -> int:
        return int(requests_per_minute or getattr(settings, "KLEVU_SYNC_REQUESTS_PER_MINUTE", 180))

    @staticmethod
    def _use_external_worker() -> bool:
        return bool(getattr(settings, "KLEVU_SYNC_USE_EXTERNAL_WORKER", False))

    @staticmethod
    def _worker_poll_seconds() -> float:
        return max(0.25, float(getattr(settings, "KLEVU_SYNC_WORKER_POLL_SECONDS", 5.0)))

    @staticmethod
    def _as_optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _build_run_config_snapshot(
        self,
        *,
        page_size: int,
        max_pages: int | None,
        requests_per_minute: int | None,
        stop_after_pages: int | None,
    ) -> Dict[str, Any]:
        return {
            "page_size": int(page_size),
            "max_pages": None if max_pages is None else int(max_pages),
            "requests_per_minute": self._resolved_rpm(requests_per_minute),
            "stop_after_pages": None if stop_after_pages is None else int(stop_after_pages),
            "payload_max_bytes": int(getattr(settings, "KLEVU_SYNC_PAYLOAD_MAX_BYTES", 2 * 1024 * 1024)),
            "disable_grouping": bool(getattr(settings, "KLEVU_SYNC_DISABLE_GROUPING", True)),
            "bulk_eav_enabled": bool(getattr(settings, "KLEVU_SYNC_BULK_EAV_ENABLED", True)),
            "row_savepoint_enabled": bool(getattr(settings, "KLEVU_SYNC_ROW_SAVEPOINT_ENABLED", True)),
            "commit_every_pages": max(1, int(getattr(settings, "KLEVU_SYNC_COMMIT_EVERY_PAGES", 1))),
            "cancel_check_every_pages": max(1, int(getattr(settings, "KLEVU_SYNC_CANCEL_CHECK_EVERY_PAGES", 1))),
            "defer_search_text": bool(getattr(settings, "KLEVU_SYNC_DEFER_SEARCH_TEXT", False)),
        }

    async def _throttle(self, requests_per_minute: int) -> None:
        rpm = max(1, int(requests_per_minute))
        min_interval = 60.0 / float(rpm)
        now = time.monotonic()
        wait_for = min_interval - (now - self._last_request_ts)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        self._last_request_ts = time.monotonic()

    async def _request_page(
        self,
        *,
        client: httpx.AsyncClient,
        payload: Dict[str, Any],
        endpoint: str,
        max_retries: int,
        backoff_base_seconds: float,
        stats: KlevuSyncStats,
    ) -> Dict[str, Any]:
        retries = max(0, int(max_retries))
        attempt = 0
        while True:
            try:
                response = await client.post(endpoint, headers={"Content-Type": "application/json"}, json=payload)
            except httpx.HTTPError as exc:
                if attempt >= retries:
                    raise HTTPException(status_code=502, detail=f"Klevu request failed: {exc}") from exc
                stats.backoff_count += 1
                await asyncio.sleep(float(backoff_base_seconds) * (2**attempt) + random.uniform(0, 0.2))
                attempt += 1
                continue
            if response.status_code == 429:
                if attempt >= retries:
                    raise HTTPException(status_code=429, detail="Klevu rate limit exceeded after retries.")
                retry_after = response.headers.get("Retry-After")
                if retry_after and str(retry_after).strip().isdigit():
                    sleep_seconds = max(float(retry_after), 0.5)
                else:
                    sleep_seconds = float(backoff_base_seconds) * (2**attempt) + random.uniform(0, 0.3)
                stats.backoff_count += 1
                await asyncio.sleep(sleep_seconds)
                attempt += 1
                continue
            if response.status_code == 500:
                raise HTTPException(
                    status_code=502,
                    detail="Klevu returned 500. Validate request JSON body structure and required fields.",
                )
            if response.is_error:
                raise HTTPException(
                    status_code=502,
                    detail=f"Klevu request failed with status {response.status_code}: {response.text[:300]}",
                )
            try:
                return response.json()
            except ValueError as exc:
                raise HTTPException(status_code=502, detail="Klevu response is not valid JSON.") from exc

    def _apply_run_stats(
        self,
        run: KlevuSyncRun,
        *,
        stats: KlevuSyncStats,
        current_offset: int,
    ) -> None:
        run.current_offset = int(current_offset)
        run.last_success_offset = int(stats.last_offset)
        run.fetched_records = int(stats.fetched_records)
        run.created = int(stats.created)
        run.updated = int(stats.updated)
        run.skipped = int(stats.skipped)
        run.failed = int(stats.failed)
        run.backoff_count = int(stats.backoff_count)
        run.request_count = int(stats.request_count)
        run.updated_at = self._now_utc()

    @staticmethod
    def _stale_running_threshold_seconds() -> int:
        minutes = max(1, int(getattr(settings, "KLEVU_SYNC_STALE_RUNNING_MINUTES", 10)))
        return minutes * 60

    def _active_background_task(self, run_id: UUID) -> asyncio.Task[None] | None:
        task = self._background_tasks.get(run_id)
        if task is None:
            return None
        if task.done():
            self._background_tasks.pop(run_id, None)
            return None
        return task

    def _is_stale_active_run(self, run: KlevuSyncRun) -> bool:
        if run.status not in self._ACTIVE_RUN_STATUSES:
            return False
        if run.status == KlevuSyncRunStatus.pending and self._use_external_worker():
            return False
        last_update = run.updated_at or run.started_at
        if last_update is None:
            return True
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)
        age_seconds = (self._now_utc() - last_update).total_seconds()
        return age_seconds >= float(self._stale_running_threshold_seconds())

    async def _try_finalize_orphan_active_run(
        self,
        db: AsyncSession,
        *,
        run: KlevuSyncRun,
        terminal_status: KlevuSyncRunStatus,
        reason: str,
    ) -> bool:
        if run.status not in self._ACTIVE_RUN_STATUSES:
            return False
        if self._active_background_task(run.id) is not None:
            return False
        if not self._is_stale_active_run(run):
            return False

        previous_status = run.status.value if hasattr(run.status, "value") else str(run.status)
        now = self._now_utc()
        run.status = terminal_status
        run.cancel_requested = False
        run.completed_at = now
        run.updated_at = now
        if not run.error_summary:
            run.error_summary = reason[:2000]
        await db.commit()
        await db.refresh(run)
        logger.warning(
            "Recovered orphan Klevu sync run: run_id=%s previous_status=%s new_status=%s",
            run.id,
            previous_status,
            terminal_status.value,
        )
        return True

    async def _sync_loop(
        self,
        db: AsyncSession,
        *,
        page_size: int,
        max_pages: int | None,
        requests_per_minute: int,
        start_offset: int,
        stop_after_pages: int | None,
        run: KlevuSyncRun | None,
    ) -> Dict[str, Any]:
        api_key = self._clean_text(getattr(settings, "KLEVU_JS_API_KEY", ""))
        if not api_key:
            raise HTTPException(status_code=400, detail="KLEVU_JS_API_KEY is not configured.")

        endpoint = (
            self._clean_text(getattr(settings, "KLEVU_API_ENDPOINT", ""))
            or "https://eucs30v2.ksearchnet.com/cs/v2/search"
        )
        max_payload_bytes = int(getattr(settings, "KLEVU_SYNC_PAYLOAD_MAX_BYTES", 2 * 1024 * 1024))
        timeout_seconds = float(getattr(settings, "KLEVU_SYNC_TIMEOUT_SECONDS", 30.0))
        max_retries = int(getattr(settings, "KLEVU_SYNC_MAX_RETRIES", 5))
        backoff_base_seconds = float(getattr(settings, "KLEVU_SYNC_BACKOFF_BASE_SECONDS", 0.5))
        page_cap = int(getattr(settings, "KLEVU_SYNC_PAGE_SIZE_MAX", 100))
        effective_page_size = min(max(int(page_size), 1), page_cap, 100)
        commit_every_pages = max(1, int(getattr(settings, "KLEVU_SYNC_COMMIT_EVERY_PAGES", 1)))
        cancel_check_every_pages = max(1, int(getattr(settings, "KLEVU_SYNC_CANCEL_CHECK_EVERY_PAGES", 1)))

        stats = KlevuSyncStats.from_run(run) if run is not None else KlevuSyncStats()
        offset = max(int(start_offset), 0)
        pages_processed = 0
        group_cache: Dict[str, UUID] = {}
        pages_since_commit = 0
        force_commit = False

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            while True:
                if max_pages is not None and pages_processed >= int(max_pages):
                    break
                if stop_after_pages is not None and pages_processed >= int(stop_after_pages):
                    if run is not None:
                        run.status = KlevuSyncRunStatus.stopped
                        force_commit = True
                    break

                if (
                    run is not None
                    and (pages_processed % cancel_check_every_pages) == 0
                ):
                    with db.no_autoflush:
                        cancel_requested = bool(
                            (
                                await db.execute(
                                    select(KlevuSyncRun.cancel_requested).where(KlevuSyncRun.id == run.id)
                                )
                            ).scalar_one_or_none()
                            or False
                        )
                    if cancel_requested:
                        run.status = KlevuSyncRunStatus.cancelled
                        force_commit = True
                        break

                payload = self._build_payload(api_key=api_key, limit=effective_page_size, offset=offset)
                self._ensure_payload_size(payload, max_bytes=max_payload_bytes)
                await self._throttle(requests_per_minute)
                response_json = await self._request_page(
                    client=client,
                    payload=payload,
                    endpoint=endpoint,
                    max_retries=max_retries,
                    backoff_base_seconds=backoff_base_seconds,
                    stats=stats,
                )
                stats.request_count += 1
                records = self._extract_records(response_json)
                if not records:
                    break

                before_created = stats.created
                before_updated = stats.updated
                before_skipped = stats.skipped
                before_failed = stats.failed
                before_deduped = stats.deduped_legacy_rows
                await self._process_page_rows(
                    db,
                    records=records,
                    stats=stats,
                    group_cache=group_cache,
                    run_id=run.id if run is not None else None,
                    page_offset=offset,
                )
                page_created = stats.created - before_created
                page_updated = stats.updated - before_updated
                page_skipped = stats.skipped - before_skipped
                page_failed = stats.failed - before_failed
                page_deduped = stats.deduped_legacy_rows - before_deduped
                stats.fetched_records += len(records)
                stats.last_offset = offset
                run_id_label = str(run.id) if run is not None else "manual"
                logger.info(
                    (
                        "Klevu sync page processed: run_id=%s offset=%s size=%s fetched=%s "
                        "delta(created=%s updated=%s skipped=%s failed=%s deduped=%s)"
                    ),
                    run_id_label,
                    offset,
                    effective_page_size,
                    len(records),
                    page_created,
                    page_updated,
                    page_skipped,
                    page_failed,
                    page_deduped,
                )
                offset += effective_page_size
                pages_processed += 1
                pages_since_commit += 1

                if run is not None:
                    self._apply_run_stats(run, stats=stats, current_offset=offset)
                if pages_since_commit >= commit_every_pages:
                    await db.commit()
                    pages_since_commit = 0

                if len(records) < effective_page_size:
                    break

        if pages_since_commit > 0 or force_commit:
            if run is not None:
                self._apply_run_stats(run, stats=stats, current_offset=offset)
            await db.commit()

        return {
            "page_size": effective_page_size,
            "pages_processed": pages_processed,
            "next_offset": offset,
            "stats": stats,
        }

    @staticmethod
    def _serialize_run(run: KlevuSyncRun, *, include_config: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": str(run.id),
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            "page_size": run.page_size,
            "max_pages": run.max_pages,
            "current_offset": run.current_offset,
            "last_success_offset": run.last_success_offset,
            "fetched_records": run.fetched_records,
            "created": run.created,
            "updated": run.updated,
            "skipped": run.skipped,
            "failed": run.failed,
            "backoff_count": run.backoff_count,
            "request_count": run.request_count,
            "cancel_requested": bool(run.cancel_requested),
            "error_summary": run.error_summary,
        }
        if include_config:
            payload["config_snapshot"] = run.config_snapshot or {}
        return payload

    async def _ensure_no_active_run(self, db: AsyncSession, *, ignore_run_id: UUID | None = None) -> None:
        stmt = select(KlevuSyncRun).where(KlevuSyncRun.status.in_(list(self._ACTIVE_RUN_STATUSES)))
        if ignore_run_id is not None:
            stmt = stmt.where(KlevuSyncRun.id != ignore_run_id)
        active_runs = (await db.execute(stmt.order_by(desc(KlevuSyncRun.started_at)))).scalars().all()
        for existing in active_runs:
            recovered = await self._try_finalize_orphan_active_run(
                db,
                run=existing,
                terminal_status=KlevuSyncRunStatus.stopped,
                reason="Recovered stale active run after worker/task loss.",
            )
            if recovered:
                continue
            raise HTTPException(
                status_code=409,
                detail=f"A Klevu full sync is already active (run_id={existing.id}).",
            )

    @staticmethod
    def _extract_worker_runtime_overrides(run: KlevuSyncRun) -> tuple[int | None, int | None, int | None]:
        config = run.config_snapshot or {}
        requests_per_minute = KlevuRunControlMixin._as_optional_int(config.get("requests_per_minute"))
        max_pages = KlevuRunControlMixin._as_optional_int(config.get("max_pages"))
        stop_after_pages = KlevuRunControlMixin._as_optional_int(config.get("stop_after_pages"))
        return requests_per_minute, max_pages, stop_after_pages

    async def _claim_next_pending_run(self, db: AsyncSession) -> KlevuSyncRun | None:
        stmt = (
            select(KlevuSyncRun)
            .where(KlevuSyncRun.status == KlevuSyncRunStatus.pending)
            .order_by(KlevuSyncRun.started_at)
            .with_for_update(skip_locked=True)
        )
        return (await db.execute(stmt)).scalars().first()

    async def process_next_queued_full_sync_run(self) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            run = await self._claim_next_pending_run(db)
            if run is None:
                return {"claimed": False}
            requests_per_minute, max_pages, stop_after_pages = self._extract_worker_runtime_overrides(run)
            logger.info("Klevu worker claimed pending run: run_id=%s", run.id)
            result = await self._execute_full_sync_run(
                db,
                run_id=run.id,
                requests_per_minute=requests_per_minute,
                max_pages=max_pages,
                stop_after_pages=stop_after_pages,
            )
            return {"claimed": True, "run_id": str(run.id), "result": result}

    async def run_queued_full_sync_worker(
        self,
        *,
        once: bool = False,
        poll_seconds: float | None = None,
    ) -> Dict[str, Any]:
        interval = self._worker_poll_seconds() if poll_seconds is None else max(0.25, float(poll_seconds))
        processed = 0
        while True:
            try:
                item = await self.process_next_queued_full_sync_run()
            except Exception:
                logger.exception("Klevu queued full-sync worker iteration failed.")
                if once:
                    raise
                await asyncio.sleep(interval)
                continue

            if not item.get("claimed", False):
                if once:
                    return {"status": "idle", "processed": processed}
                await asyncio.sleep(interval)
                continue

            processed += 1
            if once:
                return {"status": "processed", "processed": processed, "run_id": item.get("run_id")}

    async def _run_full_sync_background(
        self,
        *,
        run_id: UUID,
        requests_per_minute: int | None,
        max_pages: int | None,
        stop_after_pages: int | None,
    ) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await self._execute_full_sync_run(
                    db,
                    run_id=run_id,
                    requests_per_minute=requests_per_minute,
                    max_pages=max_pages,
                    stop_after_pages=stop_after_pages,
                )
        except Exception:
            logger.exception("Klevu background full sync task failed: run_id=%s", run_id)
        finally:
            self._background_tasks.pop(run_id, None)

    async def _execute_full_sync_run(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        requests_per_minute: int | None,
        max_pages: int | None,
        stop_after_pages: int | None,
    ) -> Dict[str, Any]:
        run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Klevu sync run not found.")

        run.status = KlevuSyncRunStatus.running
        run.cancel_requested = False
        run.error_summary = None
        run.completed_at = None
        run.updated_at = self._now_utc()
        await db.commit()

        rpm = self._resolved_rpm(requests_per_minute)
        run_max_pages = max_pages if max_pages is not None else run.max_pages
        run.config_snapshot = self._build_run_config_snapshot(
            page_size=run.page_size,
            max_pages=run_max_pages,
            requests_per_minute=rpm,
            stop_after_pages=stop_after_pages,
        )
        try:
            result = await self._sync_loop(
                db,
                page_size=run.page_size,
                max_pages=run_max_pages,
                requests_per_minute=rpm,
                start_offset=run.current_offset or 0,
                stop_after_pages=stop_after_pages,
                run=run,
            )
            await db.refresh(run)
            if run.status == KlevuSyncRunStatus.running:
                run.status = KlevuSyncRunStatus.completed
            if run.status in {KlevuSyncRunStatus.completed, KlevuSyncRunStatus.cancelled, KlevuSyncRunStatus.stopped}:
                run.completed_at = self._now_utc()
            run.updated_at = self._now_utc()
            await db.commit()
            await db.refresh(run)
            return {
                "run": self._serialize_run(run, include_config=True),
                "runtime": {
                    "pages_processed": result["pages_processed"],
                    "next_offset": result["next_offset"],
                },
            }
        except HTTPException as exc:
            await db.rollback()
            run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
            if run is not None:
                run.status = KlevuSyncRunStatus.failed
                run.error_summary = str(exc.detail)[:2000]
                run.completed_at = self._now_utc()
                run.updated_at = self._now_utc()
                await db.commit()
            raise
        except Exception as exc:
            await db.rollback()
            logger.exception("Klevu full sync run failed: run_id=%s", run_id)
            run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
            if run is not None:
                run.status = KlevuSyncRunStatus.failed
                run.error_summary = str(exc)[:2000]
                run.completed_at = self._now_utc()
                run.updated_at = self._now_utc()
                await db.commit()
            raise HTTPException(status_code=500, detail=f"Klevu full sync failed: {exc}") from exc

    async def sync_recent_products(
        self,
        db: AsyncSession,
        *,
        max_pages: int = 10,
        page_size: int = 100,
        requests_per_minute: int | None = None,
    ) -> Dict[str, Any]:
        rpm = self._resolved_rpm(requests_per_minute)
        result = await self._sync_loop(
            db,
            page_size=page_size,
            max_pages=max_pages,
            requests_per_minute=rpm,
            start_offset=0,
            stop_after_pages=None,
            run=None,
        )
        return {
            "mode": "manual",
            "status": "completed",
            "page_size": result["page_size"],
            "pages_processed": result["pages_processed"],
            "next_offset": result["next_offset"],
            "stats": result["stats"].as_dict(),
            "requests_per_minute": rpm,
        }

    async def start_full_sync(
        self,
        db: AsyncSession,
        *,
        page_size: int = 100,
        max_pages: int | None = None,
        requests_per_minute: int | None = None,
        stop_after_pages: int | None = None,
    ) -> Dict[str, Any]:
        await self._ensure_no_active_run(db)
        page_cap = int(getattr(settings, "KLEVU_SYNC_PAGE_SIZE_MAX", 100))
        effective_page_size = min(max(int(page_size), 1), page_cap, 100)
        run = KlevuSyncRun(
            status=KlevuSyncRunStatus.pending,
            page_size=effective_page_size,
            max_pages=max_pages,
            current_offset=0,
            last_success_offset=0,
            config_snapshot=self._build_run_config_snapshot(
                page_size=effective_page_size,
                max_pages=max_pages,
                requests_per_minute=requests_per_minute,
                stop_after_pages=stop_after_pages,
            ),
            cancel_requested=False,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        if self._use_external_worker():
            logger.info("Queued Klevu full sync run for external worker: run_id=%s", run.id)
            return {"run": self._serialize_run(run, include_config=True)}

        task = asyncio.create_task(
            self._run_full_sync_background(
                run_id=run.id,
                requests_per_minute=requests_per_minute,
                max_pages=max_pages,
                stop_after_pages=stop_after_pages,
            )
        )
        self._background_tasks[run.id] = task
        return {"run": self._serialize_run(run, include_config=True)}

    async def resume_full_sync(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        max_pages: int | None = None,
        requests_per_minute: int | None = None,
        stop_after_pages: int | None = None,
    ) -> Dict[str, Any]:
        run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Klevu sync run not found.")
        await self._try_finalize_orphan_active_run(
            db,
            run=run,
            terminal_status=KlevuSyncRunStatus.stopped,
            reason="Recovered stale run before resume request.",
        )
        if run.status not in {KlevuSyncRunStatus.failed, KlevuSyncRunStatus.cancelled, KlevuSyncRunStatus.stopped}:
            raise HTTPException(status_code=400, detail=f"Run {run_id} is not resumable (status={run.status.value}).")

        await self._ensure_no_active_run(db, ignore_run_id=run_id)
        run.status = KlevuSyncRunStatus.pending
        run.error_summary = None
        run.cancel_requested = False
        run.completed_at = None
        if max_pages is not None:
            run.max_pages = max_pages
        run.config_snapshot = self._build_run_config_snapshot(
            page_size=run.page_size,
            max_pages=run.max_pages,
            requests_per_minute=requests_per_minute,
            stop_after_pages=stop_after_pages,
        )
        run.updated_at = self._now_utc()
        await db.commit()
        await db.refresh(run)

        if self._use_external_worker():
            logger.info("Queued Klevu resume run for external worker: run_id=%s", run.id)
            return {"run": self._serialize_run(run, include_config=True)}

        task = asyncio.create_task(
            self._run_full_sync_background(
                run_id=run.id,
                requests_per_minute=requests_per_minute,
                max_pages=max_pages if max_pages is not None else run.max_pages,
                stop_after_pages=stop_after_pages,
            )
        )
        self._background_tasks[run.id] = task
        return {"run": self._serialize_run(run, include_config=True)}

    async def run_full_sync_cli(
        self,
        db: AsyncSession,
        *,
        page_size: int = 100,
        max_pages: int | None = None,
        requests_per_minute: int | None = None,
        stop_after_pages: int | None = None,
        resume_run_id: UUID | None = None,
    ) -> Dict[str, Any]:
        if resume_run_id is not None:
            run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == resume_run_id))).scalar_one_or_none()
            if run is None:
                raise HTTPException(status_code=404, detail="Klevu sync run not found.")
            await self._try_finalize_orphan_active_run(
                db,
                run=run,
                terminal_status=KlevuSyncRunStatus.stopped,
                reason="Recovered stale run before CLI resume.",
            )
            if run.status not in {KlevuSyncRunStatus.failed, KlevuSyncRunStatus.cancelled, KlevuSyncRunStatus.stopped}:
                raise HTTPException(status_code=400, detail=f"Run {resume_run_id} is not resumable.")
            await self._ensure_no_active_run(db, ignore_run_id=run.id)
            run.status = KlevuSyncRunStatus.pending
            run.error_summary = None
            run.cancel_requested = False
            run.completed_at = None
            run.updated_at = self._now_utc()
            if max_pages is not None:
                run.max_pages = max_pages
            run.config_snapshot = self._build_run_config_snapshot(
                page_size=run.page_size,
                max_pages=run.max_pages,
                requests_per_minute=requests_per_minute,
                stop_after_pages=stop_after_pages,
            )
            await db.commit()
            await db.refresh(run)
            return await self._execute_full_sync_run(
                db,
                run_id=run.id,
                requests_per_minute=requests_per_minute,
                max_pages=max_pages if max_pages is not None else run.max_pages,
                stop_after_pages=stop_after_pages,
            )

        await self._ensure_no_active_run(db)
        page_cap = int(getattr(settings, "KLEVU_SYNC_PAGE_SIZE_MAX", 100))
        effective_page_size = min(max(int(page_size), 1), page_cap, 100)
        run = KlevuSyncRun(
            status=KlevuSyncRunStatus.pending,
            page_size=effective_page_size,
            max_pages=max_pages,
            current_offset=0,
            last_success_offset=0,
            cancel_requested=False,
            config_snapshot=self._build_run_config_snapshot(
                page_size=effective_page_size,
                max_pages=max_pages,
                requests_per_minute=requests_per_minute,
                stop_after_pages=stop_after_pages,
            ),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return await self._execute_full_sync_run(
            db,
            run_id=run.id,
            requests_per_minute=requests_per_minute,
            max_pages=max_pages,
            stop_after_pages=stop_after_pages,
        )

    async def get_full_sync_run(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        include_failures: bool = False,
        failure_limit: int = 50,
    ) -> Dict[str, Any]:
        run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Klevu sync run not found.")
        payload = self._serialize_run(run, include_config=True)
        if include_failures:
            stmt = (
                select(KlevuSyncFailure)
                .where(KlevuSyncFailure.run_id == run_id)
                .order_by(desc(KlevuSyncFailure.created_at))
                .limit(max(1, int(failure_limit)))
            )
            result = await db.execute(stmt)
            payload["failures"] = [
                {
                    "id": str(item.id),
                    "page_offset": item.page_offset,
                    "raw_sku": item.raw_sku,
                    "canonical_sku": item.canonical_sku,
                    "error_type": item.error_type,
                    "error_message": item.error_message,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in result.scalars().all()
            ]
        payload["failure_count"] = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(KlevuSyncFailure)
                    .where(KlevuSyncFailure.run_id == run_id)
                )
            ).scalar()
            or 0
        )
        return payload

    async def list_full_sync_runs(self, db: AsyncSession, *, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        total = int((await db.execute(select(func.count()).select_from(KlevuSyncRun))).scalar() or 0)
        safe_page, total_pages, offset = normalize_pagination(total_items=total, page=page, page_size=page_size)
        stmt = (
            select(KlevuSyncRun)
            .order_by(desc(KlevuSyncRun.started_at))
            .offset(offset)
            .limit(page_size)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return {
            "items": [self._serialize_run(item, include_config=False) for item in rows],
            "totalItems": total,
            "page": safe_page,
            "pageSize": page_size,
            "totalPages": total_pages,
        }

    async def request_full_sync_cancel(self, db: AsyncSession, *, run_id: UUID) -> Dict[str, Any]:
        run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Klevu sync run not found.")
        recovered = await self._try_finalize_orphan_active_run(
            db,
            run=run,
            terminal_status=KlevuSyncRunStatus.cancelled,
            reason="Recovered stale active run during cancel request.",
        )
        if recovered:
            return {"run": self._serialize_run(run, include_config=True), "updated": True}
        now = self._now_utc()
        if run.status in {KlevuSyncRunStatus.completed, KlevuSyncRunStatus.failed, KlevuSyncRunStatus.cancelled, KlevuSyncRunStatus.stopped}:
            updated = False
            # Healing path for older rows that reached terminal status without finalized timestamp.
            if run.completed_at is None and run.status in {KlevuSyncRunStatus.completed, KlevuSyncRunStatus.cancelled, KlevuSyncRunStatus.stopped}:
                run.completed_at = now
                updated = True
            if run.cancel_requested:
                run.cancel_requested = False
                updated = True
            if updated:
                run.updated_at = now
                await db.commit()
                await db.refresh(run)
            return {"run": self._serialize_run(run, include_config=True), "updated": updated}
        if run.status == KlevuSyncRunStatus.pending:
            run.status = KlevuSyncRunStatus.cancelled
            run.cancel_requested = False
            run.completed_at = now
            run.updated_at = now
            await db.commit()
            await db.refresh(run)
            return {"run": self._serialize_run(run, include_config=True), "updated": True}
        run.cancel_requested = True
        run.updated_at = now
        await db.commit()
        await db.refresh(run)
        return {"run": self._serialize_run(run, include_config=True), "updated": True}
