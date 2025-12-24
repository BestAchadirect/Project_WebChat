from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.core.config import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEBUG_LOG_PATH = BACKEND_ROOT / settings.LOG_DIR / settings.DEBUG_LOG_FILE


def debug_log(payload: Dict[str, Any]) -> None:
    """Append a single NDJSON line to the debug log. Never raises."""
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Never let debug logging break the request
        pass
