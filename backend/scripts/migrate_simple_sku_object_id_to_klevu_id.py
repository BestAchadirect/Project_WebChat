import argparse
import asyncio
import os
import sys
from typing import List

from sqlalchemy import func, select, text

# Allow running as a script: `python scripts/migrate_simple_sku_object_id_to_klevu_id.py`
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from app.models.product import Product


async def _count_candidates() -> int:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(func.count())
            .select_from(Product)
            .where(Product.sku.ilike("%-000000"))
            .where(Product.object_id.isnot(None))
            .where(func.btrim(Product.object_id) != "")
            .where((Product.klevu_id.is_(None)) | (func.btrim(Product.klevu_id) == ""))
        )
        return int((await db.execute(stmt)).scalar() or 0)


async def _sample_candidates(*, sample_size: int) -> List[dict]:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(
                Product.id,
                Product.sku,
                Product.master_code,
                Product.object_id,
                Product.klevu_id,
                Product.updated_at,
            )
            .where(Product.sku.ilike("%-000000"))
            .where(Product.object_id.isnot(None))
            .where(func.btrim(Product.object_id) != "")
            .where((Product.klevu_id.is_(None)) | (func.btrim(Product.klevu_id) == ""))
            .order_by(Product.updated_at.desc().nullslast(), Product.created_at.desc().nullslast())
            .limit(max(0, int(sample_size)))
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "id": str(row.id),
                "sku": row.sku,
                "master_code": row.master_code,
                "object_id": row.object_id,
                "klevu_id": row.klevu_id,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]


async def _apply(*, limit: int | None) -> int:
    async with AsyncSessionLocal() as db:
        if limit is None:
            sql = text(
                """
                UPDATE products
                SET klevu_id = object_id,
                    object_id = NULL,
                    updated_at = NOW()
                WHERE sku ILIKE '%-000000'
                  AND object_id IS NOT NULL
                  AND BTRIM(object_id) <> ''
                  AND (klevu_id IS NULL OR BTRIM(klevu_id) = '')
                """
            )
            result = await db.execute(sql)
            updated = int(result.rowcount or 0)
        else:
            capped = max(0, int(limit))
            sql = text(
                """
                WITH target AS (
                    SELECT id
                    FROM products
                    WHERE sku ILIKE '%-000000'
                      AND object_id IS NOT NULL
                      AND BTRIM(object_id) <> ''
                      AND (klevu_id IS NULL OR BTRIM(klevu_id) = '')
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                    LIMIT :limit
                )
                UPDATE products p
                SET klevu_id = p.object_id,
                    object_id = NULL,
                    updated_at = NOW()
                FROM target t
                WHERE p.id = t.id
                """
            )
            result = await db.execute(sql, {"limit": capped})
            updated = int(result.rowcount or 0)
        await db.commit()
    return updated


async def run(*, apply: bool, limit: int | None, sample_size: int) -> None:
    before = await _count_candidates()
    samples = await _sample_candidates(sample_size=sample_size)

    print(f"candidate_rows={before}")
    if samples:
        print("sample_rows:")
        for item in samples:
            print(f"  {item}")

    if not apply:
        print("dry_run=True (no DB changes). Use --apply to execute migration.")
        return

    updated = await _apply(limit=limit)
    after = await _count_candidates()
    print(f"updated_rows={updated}")
    print(f"remaining_candidates={after}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move object_id to klevu_id for simple parent SKUs ending with -000000 when klevu_id is empty."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute DB update. Without this flag, script runs in dry-run mode.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on rows to update.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="Number of sample rows to print.",
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            apply=bool(args.apply),
            limit=args.limit,
            sample_size=max(0, int(args.sample_size)),
        )
    )


if __name__ == "__main__":
    main()
