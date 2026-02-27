import argparse
import asyncio
from typing import List

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.product import Product
from app.services.catalog.projection_service import product_projection_sync_service


async def run_backfill(*, batch_size: int) -> None:
    total_synced = 0
    offset = 0
    async with AsyncSessionLocal() as db:
        while True:
            stmt = (
                select(Product.id)
                .order_by(Product.created_at.asc())
                .offset(offset)
                .limit(batch_size)
            )
            rows = (await db.execute(stmt)).all()
            ids: List[object] = [row[0] for row in rows]
            if not ids:
                break
            synced = await product_projection_sync_service.sync_products_by_ids(
                db,
                product_ids=ids,
            )
            await db.commit()
            total_synced += synced
            offset += batch_size
            print(f"backfill batch offset={offset} synced={synced} total={total_synced}")
    print(f"projection backfill completed: total_synced={total_synced}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill product_search_projection from products + EAV.")
    parser.add_argument("--batch-size", type=int, default=1000, help="Rows per batch.")
    args = parser.parse_args()
    batch_size = max(1, int(args.batch_size))
    asyncio.run(run_backfill(batch_size=batch_size))


if __name__ == "__main__":
    main()

