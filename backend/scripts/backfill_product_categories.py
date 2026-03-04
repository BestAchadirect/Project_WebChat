import argparse
import asyncio
import os
import sys
from typing import Dict

from sqlalchemy import func, select

# Allow running as a script: `python scripts/backfill_product_categories.py`
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from app.models.product import Product
from app.services.catalog.category_taxonomy_service import category_taxonomy_service


async def run_backfill(*, batch_size: int, source: str, dry_run: bool, limit: int | None) -> None:
    processed = 0
    mapped = 0
    skipped = 0
    category_cache: Dict[str, int] = {}
    offset = 0

    async with AsyncSessionLocal() as db:
        total_query = (
            select(func.count())
            .select_from(Product)
            .where(Product.attributes["category"].astext.isnot(None))
            .where(func.btrim(Product.attributes["category"].astext) != "")
        )
        total = int((await db.execute(total_query)).scalar() or 0)
        if limit is not None:
            total = min(total, max(0, int(limit)))
        print(
            f"Starting category taxonomy backfill: total={total} batch_size={batch_size} "
            f"dry_run={dry_run} source={source}"
        )

        while processed < total:
            remaining = total - processed
            page_size = min(batch_size, remaining)
            rows = (
                await db.execute(
                    select(Product.id, Product.attributes["category"].astext.label("category_value"))
                    .where(Product.attributes["category"].astext.isnot(None))
                    .where(func.btrim(Product.attributes["category"].astext) != "")
                    .order_by(Product.created_at.asc(), Product.id.asc())
                    .offset(offset)
                    .limit(page_size)
                )
            ).all()
            if not rows:
                break

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
                processed += 1

            if dry_run:
                await db.rollback()
            else:
                await db.commit()

            offset += len(rows)
            print(f"progress: processed={processed}/{total} mapped={mapped} skipped={skipped}")

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
    args = parser.parse_args()

    batch_size = max(1, int(args.batch_size))
    asyncio.run(
        run_backfill(
            batch_size=batch_size,
            source=str(args.source or "legacy_backfill").strip() or "legacy_backfill",
            dry_run=bool(args.dry_run),
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
