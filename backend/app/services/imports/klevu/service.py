from __future__ import annotations

import asyncio
from typing import Dict
from uuid import UUID

from app.models.klevu_sync import KlevuSyncRunStatus
from app.services.imports.klevu.mapping import KlevuMappingMixin
from app.services.imports.klevu.resolution import KlevuResolutionMixin
from app.services.imports.klevu.run_control import KlevuRunControlMixin
from app.services.imports.klevu.types import KlevuSyncStats, PageLookupContext, ProductResolution
from app.services.imports.klevu.upsert import KlevuUpsertMixin


class KlevuProductSyncService(
    KlevuRunControlMixin,
    KlevuUpsertMixin,
    KlevuResolutionMixin,
    KlevuMappingMixin,
):
    _ACTIVE_RUN_STATUSES = {KlevuSyncRunStatus.pending, KlevuSyncRunStatus.running}

    def __init__(self) -> None:
        self._last_request_ts = 0.0
        self._background_tasks: Dict[UUID, asyncio.Task[None]] = {}


klevu_product_sync_service = KlevuProductSyncService()

__all__ = [
    "KlevuProductSyncService",
    "KlevuSyncStats",
    "PageLookupContext",
    "ProductResolution",
    "klevu_product_sync_service",
]

