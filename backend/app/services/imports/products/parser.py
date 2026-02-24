from __future__ import annotations

from typing import Any


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        clean = value.strip()
        if not clean:
            return None
        try:
            return int(float(clean))
        except ValueError:
            return None
    return None


def parse_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        clean = value.strip()
        if not clean:
            return 0.0
        try:
            return float(clean)
        except ValueError:
            return 0.0
    return 0.0


def parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        clean = value.strip().lower()
        if not clean:
            return None
        if clean in {"1", "true", "yes", "y", "on"}:
            return True
        if clean in {"0", "false", "no", "n", "off"}:
            return False
    return None


def parse_stock_status(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    if isinstance(value, (int, float)):
        return "in_stock" if int(value) == 1 else "out_of_stock"
    if isinstance(value, str):
        clean = value.strip().lower()
        if not clean:
            return None
        if clean in {"1", "in_stock", "true", "yes", "y"}:
            return "in_stock"
        if clean in {"0", "out_of_stock", "false", "no", "n"}:
            return "out_of_stock"
    return None
