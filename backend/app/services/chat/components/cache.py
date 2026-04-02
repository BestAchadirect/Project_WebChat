from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, Optional


def stable_cache_key(prefix: str, payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


class ComponentCache:
    def __init__(self) -> None:
        self._entries: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return True

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        now = time.monotonic()
        async with self._lock:
            entry = self._entries.get(str(key))
            if entry is None:
                return None
            expires_at, payload = entry
            if expires_at <= now:
                self._entries.pop(str(key), None)
                return None
            return dict(payload)

    async def set_json(self, key: str, payload: Dict[str, Any], ttl_seconds: int) -> None:
        ttl = max(1, int(ttl_seconds))
        expires_at = time.monotonic() + float(ttl)
        async with self._lock:
            self._entries[str(key)] = (expires_at, dict(payload))


component_cache = ComponentCache()
