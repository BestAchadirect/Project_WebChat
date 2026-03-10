import argparse
import asyncio
import os
import sys
from typing import Dict, List, Tuple

from sqlalchemy import func, select

# Allow running as a script: `python scripts/backfill_product_categories.py`
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from app.models.product import Product
from app.services.catalog.category_taxonomy_service import category_taxonomy_service


async def _load_batch(*, offset: int, limit: int) -> List[Tuple]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Product.id, Product.attributes["category"].astext.label("category_value"))
                .where(Product.attributes["category"].astext.isnot(None))
                .where(func.btrim(Product.attributes["category"].astext) != "")
                .order_by(Product.created_at.asc(), Product.id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    return list(rows)


async def _apply_batch(
    *,
    rows: List[Tuple],
    source: str,
    dry_run: bool,
    category_cache: Dict[str, int],
) -> Tuple[int, int]:
    mapped = 0
    skipped = 0
    async with AsyncSessionLocal() as db:
        for row in rows:
            tokens = await category_taxonomy_service.sync_product_categories(
                db,
                product_id=row.id,
                raw_category=row.category_value,
                source=source,
                category_cache=category_cache,
                clear_when_empty=False,
            )
            if tokens:
                mapped += 1
            else:
                skipped += 1
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    return mapped, skipped


async def run_backfill(
    *,
    batch_size: int,
    source: str,
    dry_run: bool,
    limit: int | None,
    start_offset: int,
    max_retries: int,
) -> None:
    processed = 0
    mapped = 0
    skipped = 0
    category_cache: Dict[str, int] = {}
    offset = max(0, int(start_offset))

    async with AsyncSessionLocal() as db:
        total_query = (
            select(func.count())
            .select_from(Product)
            .where(Product.attributes["category"].astext.isnot(None))
            .where(func.btrim(Product.attributes["category"].astext) != "")
        )
        total_available = int((await db.execute(total_query)).scalar() or 0)

    if limit is not None:
        total_target = min(max(0, int(limit)), max(0, total_available - offset))
    else:
        total_target = max(0, total_available - offset)

    print(
        f"Starting category taxonomy backfill: total={total_target} batch_size={batch_size} "
        f"dry_run={dry_run} source={source} start_offset={offset} max_retries={max_retries}"
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
                batch_mapped, batch_skipped = await _apply_batch(
                    rows=rows,
                    source=source,
                    dry_run=dry_run,
                    category_cache=category_cache,
                )
                mapped += batch_mapped
                skipped += batch_skipped
                processed += len(rows)
                offset += len(rows)
                print(f"progress: processed={processed}/{total_target} mapped={mapped} skipped={skipped}")
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
        "Category taxonomy backfill completed: "
        f"processed={processed} mapped={mapped} skipped={skipped} dry_run={dry_run}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill product category taxonomy mappings.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per DB batch commit.")
    parser.add_argument("--source", type=str, default="legacy_backfill", help="Source label for product_categories.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of products to process.")
    parser.add_argument("--dry-run", action="store_true", help="Process rows but rollback changes.")
    parser.add_argument("--start-offset", type=int, default=0, help="Resume from row offset in sorted product set.")
    parser.add_argument("--max-retries", type=int, default=5, help="Retries per batch on transient DB errors.")
    args = parser.parse_args()

    batch_size = max(1, int(args.batch_size))
    asyncio.run(
        run_backfill(
            batch_size=batch_size,
            source=str(args.source or "legacy_backfill").strip() or "legacy_backfill",
            dry_run=bool(args.dry_run),
            limit=args.limit,
            start_offset=args.start_offset,
            max_retries=max(0, int(args.max_retries)),
        )
    )


if __name__ == "__main__":
    main()
