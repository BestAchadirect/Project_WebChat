from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.product import Product
from app.services.imports.service import data_import_service


async def run(*, batch_size: int) -> int:
    safe_batch = max(1, int(batch_size))
    model = str(getattr(settings, "PRODUCT_EMBEDDING_MODEL", "") or "").strip()
    if not model:
        raise SystemExit("PRODUCT_EMBEDDING_MODEL is empty.")

    async with AsyncSessionLocal() as db:
        total = int((await db.execute(select(func.count()).select_from(Product))).scalar() or 0)
        print(f"embedding_model={model}")
        print(f"total_products={total}")
        if total <= 0:
            print("done=true")
            return 0

        processed = 0
        embedded = 0
        skipped = 0
        last_id: UUID | None = None

        while True:
            stmt = select(Product).order_by(Product.id).limit(safe_batch)
            if last_id is not None:
                stmt = stmt.where(Product.id > last_id)
            result = await db.execute(stmt)
            products = result.scalars().all()
            if not products:
                break

            last_id = products[-1].id
            updated_count, skipped_count = await data_import_service._process_product_embedding_page(
                db,
                products=products,
                model=model,
            )
            await db.commit()

            processed += len(products)
            embedded += int(updated_count)
            skipped += int(skipped_count)
            print(f"processed={processed}/{total} embedded={embedded} skipped_unchanged={skipped}")

    print("done=true")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill product embeddings for all products.")
    parser.add_argument("--batch-size", type=int, default=500, help="Number of products per embedding batch.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run(batch_size=args.batch_size))


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
