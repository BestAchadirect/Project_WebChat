import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.models.product import Product
from app.services.data_import_service import (
    data_import_service,
    ATTRIBUTE_COLUMNS,
    SEARCH_KEYWORD_COLUMNS,
)


def _build_attributes(product: Product) -> dict:
    attributes = dict(product.attributes or {})
    for key in ATTRIBUTE_COLUMNS:
        value = getattr(product, key, None)
        if value is not None:
            attributes[key] = value
    return attributes


async def rebuild(batch_size: int = 500) -> None:
    async with AsyncSessionLocal() as db:
        total = await db.scalar(select(func.count()).select_from(Product)) or 0
        updated = 0
        offset = 0

        while offset < total:
            result = await db.execute(
                select(Product).order_by(Product.created_at).offset(offset).limit(batch_size)
            )
            products = result.scalars().all()
            if not products:
                break

            for product in products:
                display_name = product.master_code or product.sku
                legacy_skus = list(product.legacy_sku or [])
                attributes = _build_attributes(product)
                synonyms = data_import_service._build_search_synonyms(attributes)
                search_text = data_import_service._build_search_text(
                    display_name=display_name,
                    sku=product.sku,
                    object_id=product.object_id,
                    description=product.description,
                    legacy_skus=legacy_skus,
                    synonyms=synonyms,
                    attributes=attributes,
                    attribute_columns=ATTRIBUTE_COLUMNS,
                )
                search_keywords = data_import_service._build_search_keywords(
                    display_name=display_name,
                    sku=product.sku,
                    legacy_skus=legacy_skus,
                    attributes=attributes,
                    keyword_columns=SEARCH_KEYWORD_COLUMNS,
                )
                search_hash = data_import_service._hash_text(search_text)

                if (
                    product.search_text != search_text
                    or product.search_hash != search_hash
                    or product.search_keywords != search_keywords
                ):
                    product.search_text = search_text
                    product.search_hash = search_hash
                    product.search_keywords = search_keywords
                    updated += 1

            await db.commit()
            offset += batch_size
            print(f"Processed {min(offset, total)}/{total} products...")

        print(f"Done. Updated {updated} of {total} products.")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(rebuild())
