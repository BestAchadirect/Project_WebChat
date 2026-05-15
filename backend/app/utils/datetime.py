from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def utc_now_iso_z() -> str:
    return utc_now_iso().replace("+00:00", "Z")
