import argparse
import asyncio
import os
import sys
from typing import Any, Dict, List, Tuple

from sqlalchemy import func, select

# Allow running as a script: `python scripts/backfill_category_facet_eav.py`
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from app.models.category import Category, ProductCategory
from app.services.catalog.attributes_service import eav_service


async def _load_batch(*, offset: int, limit: int) -> List[Tuple[Any, List[str]]]:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(
                ProductCategory.product_id.label("product_id"),
                func.array_agg(func.distinct(Category.label)).label("labels"),
            )
            .join(Category, Category.id == ProductCategory.category_id)
            .where(Category.label.isnot(None))
            .where(func.btrim(Category.label) != "")
            .group_by(ProductCategory.product_id)
            .order_by(ProductCategory.product_id.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
    parsed: List[Tuple[Any, List[str]]] = []
    for row in rows:
        labels = [str(label).strip() for label in (row.labels or []) if str(label).strip()]
        parsed.append((row.product_id, labels))
    return parsed


async def _apply_batch(
    *,
    rows: List[Tuple[Any, List[str]]],
    dry_run: bool,
) -> Dict[str, int]:
    eav_rows = [
        (product_id, "category", labels)
        for product_id, labels in rows
        if product_id is not None and labels
    ]
    async with AsyncSessionLocal() as db:
        metrics = await eav_service.bulk_upsert_product_attribute_rows(
            db,
            rows=eav_rows,
            drop_empty=True,
        )
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    return {
        "rows_total": int(metrics.get("rows_total", 0)),
        "unique_pairs": int(metrics.get("unique_pairs", 0)),
        "insert_rows": int(metrics.get("insert_rows", 0)),
        "drop_empty": int(metrics.get("drop_empty", 0)),
    }


async def run_backfill(
    *,
    batch_size: int,
    dry_run: bool,
    limit: int | None,
    start_offset: int,
    max_retries: int,
) -> None:
    processed = 0
    updated_products = 0
    inserted_rows = 0
    dropped_rows = 0
    offset = max(0, int(start_offset))

    async with AsyncSessionLocal() as db:
        total_query = (
            select(func.count(func.distinct(ProductCategory.product_id)))
            .select_from(ProductCategory)
            .join(Category, Category.id == ProductCategory.category_id)
            .where(Category.label.isnot(None))
            .where(func.btrim(Category.label) != "")
        )
        total_available = int((await db.execute(total_query)).scalar() or 0)

    if limit is not None:
        total_target = min(max(0, int(limit)), max(0, total_available - offset))
    else:
        total_target = max(0, total_available - offset)

    print(
        f"Starting category EAV backfill: total={total_target} batch_size={batch_size} "
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
                processed += len(rows)
                offset += len(rows)
                updated_products += metrics["unique_pairs"]
                inserted_rows += metrics["insert_rows"]
                dropped_rows += metrics["drop_empty"]

                print(
                    "progress: "
                    f"processed={processed}/{total_target} "
                    f"updated_products={updated_products} "
                    f"insert_rows={inserted_rows} "
                    f"drop_empty={dropped_rows}"
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
        "Category EAV backfill completed: "
        f"processed={processed} updated_products={updated_products} "
        f"insert_rows={inserted_rows} drop_empty={dropped_rows} dry_run={dry_run}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill EAV category facet rows from legacy product_categories."
    )
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per DB batch commit.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of products to process.")
    parser.add_argument("--dry-run", action="store_true", help="Process rows but rollback changes.")
    parser.add_argument("--start-offset", type=int, default=0, help="Resume from row offset in sorted product set.")
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
