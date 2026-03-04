from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import List
from uuid import UUID

from sqlalchemy import func, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.db.session import AsyncSessionLocal
from app.models.product import Product
from app.services.catalog.projection_service import product_projection_sync_service


async def run(*, batch_size: int) -> int:
    safe_batch = max(1, int(batch_size))
    async with AsyncSessionLocal() as db:
        total = int((await db.execute(select(func.count()).select_from(Product))).scalar() or 0)
        print(f"total_products={total}")
        if total <= 0:
            print("done=true")
            return 0

        processed = 0
        last_id: UUID | None = None
        while True:
            stmt = select(Product.id).order_by(Product.id).limit(safe_batch)
            if last_id is not None:
                stmt = stmt.where(Product.id > last_id)
            result = await db.execute(stmt)
            ids: List[UUID] = list(result.scalars().all())
            if not ids:
                break

            await product_projection_sync_service.sync_products_by_ids(
                db,
                product_ids=ids,
            )
            await db.commit()

            processed += len(ids)
            last_id = ids[-1]
            print(f"processed={processed}/{total}")

    print("done=true")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill product_search_projection for all products.")
    parser.add_argument("--batch-size", type=int, default=1000, help="Number of products per projection sync batch.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run(batch_size=args.batch_size))


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
