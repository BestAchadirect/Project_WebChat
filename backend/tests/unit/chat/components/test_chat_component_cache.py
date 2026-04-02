from __future__ import annotations

import pytest

from app.services.chat.components.cache import ComponentCache, stable_cache_key


@pytest.mark.asyncio
async def test_component_cache_roundtrip() -> None:
    cache = ComponentCache()

    assert await cache.get_json("key") is None
    await cache.set_json("key", {"v": 1}, ttl_seconds=30)
    assert await cache.get_json("key") == {"v": 1}


def test_stable_cache_key_is_deterministic() -> None:
    key_a = stable_cache_key("prefix", {"b": 2, "a": 1})
    key_b = stable_cache_key("prefix", {"a": 1, "b": 2})
    assert key_a == key_b
