from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.semantic_cache import SemanticCache

logger = get_logger(__name__)


@dataclass(frozen=True)
class SemanticCacheHit:
    entry: SemanticCache
    distance: float


class SemanticCacheService:
    def _max_distance(self) -> float:
        similarity = float(getattr(settings, "SEMANTIC_CACHE_THRESHOLD", 0.96))
        similarity = max(0.0, min(1.0, similarity))
        return max(0.0, 1.0 - similarity)

    async def get_hit(
        self,
        db: AsyncSession,
        *,
        query_embedding: Sequence[float],
        reply_language: str,
        target_currency: Optional[str],
    ) -> Optional[SemanticCacheHit]:
        if not bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", True)):
            return None

        now = datetime.utcnow()
        max_distance = self._max_distance()
        if max_distance <= 0:
            return None

        distance_expr = SemanticCache.embedding.cosine_distance(query_embedding)
        stmt = (
            select(SemanticCache, distance_expr.label("distance"))
            .where(SemanticCache.reply_language == str(reply_language or ""))
            .where(SemanticCache.expires_at > now)
            .where(distance_expr <= max_distance)
            .order_by(distance_expr)
            .limit(1)
        )
        if target_currency:
            stmt = stmt.where(SemanticCache.target_currency == str(target_currency))

        result = await db.execute(stmt)
        row = result.first()
        if not row:
            return None
        entry, distance = row
        try:
            d = float(distance)
        except Exception:
            d = 9999.0
        return SemanticCacheHit(entry=entry, distance=d)

    async def save_hit(
        self,
        db: AsyncSession,
        *,
        query_text: str,
        query_embedding: Sequence[float],
        response_json: Dict[str, Any],
        reply_language: str,
        target_currency: Optional[str],
    ) -> None:
        if not bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", True)):
            return

        ttl_days = int(getattr(settings, "SEMANTIC_CACHE_TTL_DAYS", 7))
        ttl_days = max(1, min(365, ttl_days))
        now = datetime.utcnow()
        expires_at = now + timedelta(days=ttl_days)

        entry = SemanticCache(
            query_text=query_text,
            embedding=list(query_embedding),
            response_json=response_json,
            reply_language=str(reply_language or ""),
            target_currency=str(target_currency) if target_currency else None,
            created_at=now,
            expires_at=expires_at,
        )
        try:
            db.add(entry)
            await db.commit()
        except Exception as exc:
            # Cache writes are best-effort and must never block chat responses.
            try:
                await db.rollback()
            except Exception:
                pass
            logger.warning(
                "semantic cache save failed; continuing without cache",
                extra={
                    "event": "semantic_cache_save_failed",
                    "reply_language": str(reply_language or ""),
                    "target_currency": str(target_currency) if target_currency else None,
                    "error": str(exc),
                },
            )


semantic_cache_service = SemanticCacheService()

