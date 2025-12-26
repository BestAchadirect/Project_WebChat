import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.models.product import Product
from app.models.product_group import ProductGroup


async def check_counts() -> None:
    async with AsyncSessionLocal() as db:
        total_products = await db.scalar(select(func.count()).select_from(Product))
        total_groups = await db.scalar(select(func.count()).select_from(ProductGroup))
        missing_group = await db.scalar(
            select(func.count()).select_from(Product).where(Product.group_id.is_(None))
        )
        distinct_master = await db.scalar(
            select(func.count(func.distinct(Product.master_code)))
        )
        orphan_groups = await db.scalar(
            select(func.count())
            .select_from(ProductGroup)
            .outerjoin(Product, Product.group_id == ProductGroup.id)
            .where(Product.id.is_(None))
        )
        mismatch = await db.scalar(
            select(func.count())
            .select_from(Product)
            .join(ProductGroup, Product.group_id == ProductGroup.id, isouter=True)
            .where(
                ProductGroup.id.is_not(None),
                ProductGroup.master_code.is_not(None),
                Product.master_code != ProductGroup.master_code,
            )
        )

    print("Product Group Check")
    print(f"Products: {total_products or 0}")
    print(f"Groups: {total_groups or 0}")
    print(f"Distinct master_code: {distinct_master or 0}")
    print(f"Products missing group_id: {missing_group or 0}")
    print(f"Groups with no products: {orphan_groups or 0}")
    print(f"Products with master_code mismatch: {mismatch or 0}")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_counts())
