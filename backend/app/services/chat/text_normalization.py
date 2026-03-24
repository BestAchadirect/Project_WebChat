from __future__ import annotations

from typing import Any


def normalize_user_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def normalize_db_value(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_text(value: Any) -> str:
    return normalize_user_text(value)
