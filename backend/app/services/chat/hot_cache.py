from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.config import settings


@dataclass(frozen=True)
class HotCacheEntry:
    payload: Dict[str, Any]
    expires_at: float


class HotResponseCache:
    def __init__(self, *, maxsize: int, ttl_seconds: float):
        self.maxsize = max(0, int(maxsize))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._items: OrderedDict[str, HotCacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not key or self.maxsize <= 0:
            self.misses += 1
            return None
        now = time.time()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                self.misses += 1
                return None
            if entry.expires_at and entry.expires_at < now:
                self._items.pop(key, None)
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return dict(entry.payload)

    def set(self, key: str, payload: Dict[str, Any]) -> None:
        if not key or self.maxsize <= 0:
            return
        expires_at = 0.0
        if self.ttl_seconds > 0:
            expires_at = time.time() + self.ttl_seconds
        with self._lock:
            self._items[key] = HotCacheEntry(payload=dict(payload or {}), expires_at=expires_at)
            self._items.move_to_end(key)
            while len(self._items) > self.maxsize:
                self._items.popitem(last=False)

    def stats(self) -> Dict[str, Any]:
        total = int(self.hits + self.misses)
        hit_rate = float(self.hits / total) if total > 0 else 0.0
        with self._lock:
            size = len(self._items)
        return {
            "size": int(size),
            "hits": int(self.hits),
            "misses": int(self.misses),
            "hit_rate": round(hit_rate, 4),
        }


def build_feature_flags_hash(flags: Dict[str, Any]) -> str:
    serialized = json.dumps(flags or {}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def build_cache_key(
    *,
    text: str,
    locale: str,
    currency: str,
    channel: str,
    catalog_version: str,
    feature_flags_hash: str,
    prompt_version: str,
    cache_version: str,
) -> str:
    normalized_text = " ".join(str(text or "").strip().lower().split())
    normalized_locale = str(locale or "").strip().lower()
    normalized_currency = str(currency or "").strip().upper()
    normalized_channel = str(channel or "").strip().lower()
    normalized_catalog = str(catalog_version or "").strip().lower()
    normalized_flags = str(feature_flags_hash or "").strip().lower()
    normalized_prompt = str(prompt_version or "").strip().lower()
    normalized_cache = str(cache_version or "").strip().lower()

    raw = (
        f"{normalized_text}|{normalized_locale}|{normalized_currency}|"
        f"{normalized_channel}|{normalized_catalog}|{normalized_flags}|"
        f"{normalized_prompt}|{normalized_cache}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


hot_response_cache = HotResponseCache(
    maxsize=int(getattr(settings, "CHAT_HOT_CACHE_MAX_ITEMS", 3000)),
    ttl_seconds=float(getattr(settings, "CHAT_HOT_CACHE_TTL_SECONDS", 300)),
)

