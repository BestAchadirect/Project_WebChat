from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.chat.components.cache import RedisComponentCache, stable_cache_key


@pytest.mark.asyncio
async def test_redis_cache_graceful_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_REDIS_CACHE_ENABLED", False)
    cache = RedisComponentCache()

    assert await cache.get_json("key") is None
    await cache.set_json("key", {"v": 1}, ttl_seconds=30)


def test_stable_cache_key_is_deterministic() -> None:
    key_a = stable_cache_key("prefix", {"b": 2, "a": 1})
    key_b = stable_cache_key("prefix", {"a": 1, "b": 2})
    assert key_a == key_b
