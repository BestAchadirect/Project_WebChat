from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.models.klevu_sync import KlevuSyncRun
from app.models.product import Product


@dataclass
class KlevuSyncStats:
    fetched_records: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    request_count: int = 0
    backoff_count: int = 0
    last_offset: int = 0
    deduped_legacy_rows: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "fetched_records": int(self.fetched_records),
            "created": int(self.created),
            "updated": int(self.updated),
            "skipped": int(self.skipped),
            "failed": int(self.failed),
            "request_count": int(self.request_count),
            "backoff_count": int(self.backoff_count),
            "last_offset": int(self.last_offset),
            "deduped_legacy_rows": int(self.deduped_legacy_rows),
        }

    @classmethod
    def from_run(cls, run: KlevuSyncRun) -> "KlevuSyncStats":
        return cls(
            fetched_records=int(run.fetched_records or 0),
            created=int(run.created or 0),
            updated=int(run.updated or 0),
            skipped=int(run.skipped or 0),
            failed=int(run.failed or 0),
            request_count=int(run.request_count or 0),
            backoff_count=int(run.backoff_count or 0),
            last_offset=int(run.last_success_offset or 0),
            deduped_legacy_rows=0,
        )


@dataclass
class ProductResolution:
    selected: Optional[Product]
    duplicates: List[Product]


@dataclass
class PageLookupContext:
    products_by_sku: Dict[str, List[Product]]
    products_by_object_id: Dict[str, List[Product]]
    products_by_klevu_id: Dict[str, List[Product]]

