from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

try:
    from redis.asyncio import Redis  # type: ignore
except Exception:  # pragma: no cover - optional dependency in some environments
    Redis = None  # type: ignore


def stable_cache_key(prefix: str, payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


class RedisComponentCache:
    def __init__(self) -> None:
        self._client: Optional[Redis] = None

    @property
    def enabled(self) -> bool:
        return bool(getattr(settings, "CHAT_REDIS_CACHE_ENABLED", False))

    async def _ensure_client(self) -> Optional[Redis]:
        if not self.enabled:
            return None
        if Redis is None:
            return None
        if self._client is not None:
            return self._client
        url = str(getattr(settings, "CHAT_REDIS_URL", "") or "").strip()
        if not url:
            return None
        try:
            self._client = Redis.from_url(url, decode_responses=True)
            await self._client.ping()
            return self._client
        except Exception as exc:
            logger.warning("redis unavailable; continuing without redis cache: %s", exc)
            self._client = None
            return None

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        client = await self._ensure_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            if not raw:
                return None
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except Exception as exc:
            logger.warning("redis get_json failed for key=%s: %s", key, exc)
            return None

    async def set_json(self, key: str, payload: Dict[str, Any], ttl_seconds: int) -> None:
        client = await self._ensure_client()
        if client is None:
            return
        try:
            ttl = max(1, int(ttl_seconds))
            await client.set(key, json.dumps(payload, ensure_ascii=True), ex=ttl)
        except Exception as exc:
            logger.warning("redis set_json failed for key=%s: %s", key, exc)


redis_component_cache = RedisComponentCache()

