import argparse
import asyncio
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Tuple
from uuid import UUID

from sqlalchemy import func, or_, select

# Allow running as a script: `python scripts/backfill_knowledge_chunk_tags.py`
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from app.models.knowledge import KnowledgeArticle, KnowledgeChunk, KnowledgeChunkTag
from app.services.knowledge.enrichment import enrich_chunk


async def _load_batch(*, offset: int, limit: int) -> List[Tuple[Any, ...]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    KnowledgeChunk.id.label("chunk_id"),
                    KnowledgeChunk.article_id,
                    KnowledgeChunk.version,
                    KnowledgeChunk.chunk_index,
                    KnowledgeArticle.title,
                    KnowledgeArticle.category,
                    KnowledgeChunk.chunk_text,
                )
                .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
                .where(or_(KnowledgeArticle.active_version.is_(None), KnowledgeChunk.version == KnowledgeArticle.active_version))
                .order_by(
                    KnowledgeChunk.article_id.asc(),
                    KnowledgeChunk.version.asc(),
                    KnowledgeChunk.chunk_index.asc(),
                    KnowledgeChunk.id.asc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
    return list(rows)


async def _apply_batch(*, rows: List[Tuple[Any, ...]], dry_run: bool) -> Dict[str, int]:
    chunk_ids = [row.chunk_id for row in rows if row.chunk_id is not None]
    article_map = {
        row.article_id: {"title": row.title, "category": row.category}
        for row in rows
    }
    existing_tags: dict[UUID, set[str]] = defaultdict(set)
    async with AsyncSessionLocal() as db:
        if chunk_ids:
            existing_rows = (
                await db.execute(
                    select(KnowledgeChunkTag.chunk_id, KnowledgeChunkTag.tag).where(KnowledgeChunkTag.chunk_id.in_(chunk_ids))
                )
            ).all()
            for row in existing_rows:
                existing_tags[row.chunk_id].add(str(row.tag))

        inserted = 0
        skipped = 0
        for row in rows:
            enrichment = await enrich_chunk(
                db=db,
                chunk_id=row.chunk_id,
                article_title=article_map.get(row.article_id, {}).get("title"),
                article_category=article_map.get(row.article_id, {}).get("category"),
                chunk_text=row.chunk_text,
                generated_by="backfill",
            )
            tags = list(enrichment.get("tags") or [])
            existing = existing_tags.get(row.chunk_id, set())
            for tag in tags:
                if tag in existing:
                    skipped += 1
                    continue
                db.add(KnowledgeChunkTag(chunk_id=row.chunk_id, tag=tag))
                inserted += 1

        if dry_run:
            await db.rollback()
        else:
            await db.commit()

    return {"inserted": inserted, "skipped": skipped}


async def run_backfill(
    *,
    batch_size: int,
    dry_run: bool,
    limit: int | None,
    start_offset: int,
    max_retries: int,
) -> None:
    processed = 0
    inserted = 0
    skipped = 0
    offset = max(0, int(start_offset))

    async with AsyncSessionLocal() as db:
        total_query = (
            select(func.count())
            .select_from(KnowledgeChunk)
            .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
            .where(or_(KnowledgeArticle.active_version.is_(None), KnowledgeChunk.version == KnowledgeArticle.active_version))
        )
        total_available = int((await db.execute(total_query)).scalar() or 0)

    if limit is not None:
        total_target = min(max(0, int(limit)), max(0, total_available - offset))
    else:
        total_target = max(0, total_available - offset)

    print(
        f"Starting knowledge chunk enrichment backfill: total={total_target} batch_size={batch_size} "
        f"dry_run={dry_run} start_offset={offset} max_retries={max_retries}"
    )

    while processed < total_target:
        remaining = total_target - processed
        page_size = min(batch_size, remaining)
        attempt = 0
        while True:
            try:
                rows = await _load_batch(offset=offset, limit=page_size)
                if not rows:
                    print("No more rows returned; stopping early.")
                    processed = total_target
                    break
                metrics = await _apply_batch(rows=rows, dry_run=dry_run)
                inserted += metrics["inserted"]
                skipped += metrics["skipped"]
                processed += len(rows)
                offset += len(rows)
                print(
                    f"progress: processed={processed}/{total_target} "
                    f"inserted={inserted} skipped={skipped}"
                )
                break
            except Exception as exc:
                attempt += 1
                if attempt > max_retries:
                    raise RuntimeError(
                        f"Backfill failed at offset={offset} after {max_retries} retries: {exc}"
                    ) from exc
                sleep_seconds = min(10.0, 1.0 * attempt)
                print(
                    f"batch retry: offset={offset} attempt={attempt}/{max_retries} "
                    f"error={exc}; sleeping={sleep_seconds}s"
                )
                await asyncio.sleep(sleep_seconds)

    print(
        "Knowledge chunk enrichment backfill completed: "
        f"processed={processed} inserted={inserted} skipped={skipped} dry_run={dry_run}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill knowledge chunk enrichment from existing DB content.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per DB batch commit.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of chunks to process.")
    parser.add_argument("--dry-run", action="store_true", help="Process rows but rollback changes.")
    parser.add_argument("--start-offset", type=int, default=0, help="Resume from row offset in sorted chunk set.")
    parser.add_argument("--max-retries", type=int, default=5, help="Retries per batch on transient DB errors.")
    args = parser.parse_args()

    asyncio.run(
        run_backfill(
            batch_size=max(1, int(args.batch_size)),
            dry_run=bool(args.dry_run),
            limit=args.limit,
            start_offset=max(0, int(args.start_offset)),
            max_retries=max(0, int(args.max_retries)),
        )
    )


if __name__ == "__main__":
    main()
