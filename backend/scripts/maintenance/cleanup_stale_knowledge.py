import argparse
import asyncio
from typing import Tuple

from sqlalchemy import text

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal

logger = get_logger(__name__)


COUNT_STALE_EMBEDDINGS_SQL = text(
    """
    SELECT COUNT(*)
    FROM knowledge_embeddings ke
    JOIN knowledge_chunks kc ON kc.id = ke.chunk_id
    JOIN knowledge_articles ka ON ka.id = kc.article_id
    WHERE ka.active_version IS NOT NULL
      AND kc.version < ka.active_version
      AND kc.created_at < (NOW() - (:retention_days || ' days')::interval)
    """
)

COUNT_STALE_CHUNKS_SQL = text(
    """
    SELECT COUNT(*)
    FROM knowledge_chunks kc
    JOIN knowledge_articles ka ON ka.id = kc.article_id
    WHERE ka.active_version IS NOT NULL
      AND kc.version < ka.active_version
      AND kc.created_at < (NOW() - (:retention_days || ' days')::interval)
      AND NOT EXISTS (
          SELECT 1
          FROM knowledge_embeddings ke
          WHERE ke.chunk_id = kc.id
      )
    """
)

DELETE_STALE_EMBEDDINGS_SQL = text(
    """
    DELETE FROM knowledge_embeddings ke
    USING knowledge_chunks kc, knowledge_articles ka
    WHERE ke.chunk_id = kc.id
      AND kc.article_id = ka.id
      AND ka.active_version IS NOT NULL
      AND kc.version < ka.active_version
      AND kc.created_at < (NOW() - (:retention_days || ' days')::interval)
    """
)

DELETE_STALE_CHUNKS_SQL = text(
    """
    DELETE FROM knowledge_chunks kc
    USING knowledge_articles ka
    WHERE kc.article_id = ka.id
      AND ka.active_version IS NOT NULL
      AND kc.version < ka.active_version
      AND kc.created_at < (NOW() - (:retention_days || ' days')::interval)
      AND NOT EXISTS (
          SELECT 1
          FROM knowledge_embeddings ke
          WHERE ke.chunk_id = kc.id
      )
    """
)


async def _count_candidates(retention_days: int) -> Tuple[int, int]:
    async with AsyncSessionLocal() as db:
        emb_count = int((await db.execute(COUNT_STALE_EMBEDDINGS_SQL, {"retention_days": retention_days})).scalar() or 0)
        chunk_count = int((await db.execute(COUNT_STALE_CHUNKS_SQL, {"retention_days": retention_days})).scalar() or 0)
        return emb_count, chunk_count


async def _cleanup(retention_days: int) -> Tuple[int, int]:
    async with AsyncSessionLocal() as db:
        emb_result = await db.execute(DELETE_STALE_EMBEDDINGS_SQL, {"retention_days": retention_days})
        chunk_result = await db.execute(DELETE_STALE_CHUNKS_SQL, {"retention_days": retention_days})
        await db.commit()
        emb_deleted = int(emb_result.rowcount or 0)
        chunk_deleted = int(chunk_result.rowcount or 0)
        return emb_deleted, chunk_deleted


async def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup stale knowledge chunks/embeddings older than active_version.")
    parser.add_argument("--retention-days", type=int, default=14, help="Keep stale data newer than this many days.")
    parser.add_argument("--dry-run", action="store_true", help="Only print candidates; do not delete.")
    args = parser.parse_args()

    retention_days = max(1, int(args.retention_days))
    emb_count, chunk_count = await _count_candidates(retention_days)
    logger.info(
        "stale-knowledge candidates | retention_days=%s embeddings=%s chunks=%s",
        retention_days,
        emb_count,
        chunk_count,
    )

    if args.dry_run:
        print(
            f"[dry-run] retention_days={retention_days} "
            f"stale_embeddings={emb_count} stale_chunks={chunk_count}"
        )
        return

    emb_deleted, chunk_deleted = await _cleanup(retention_days)
    print(
        f"[cleanup] retention_days={retention_days} "
        f"deleted_embeddings={emb_deleted} deleted_chunks={chunk_deleted}"
    )


if __name__ == "__main__":
    asyncio.run(main())

