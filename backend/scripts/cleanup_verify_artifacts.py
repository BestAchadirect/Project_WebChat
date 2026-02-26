import argparse
import asyncio
import os
import sys
from typing import List

from sqlalchemy import select, update

# Assume running from `backend` directory.
sys.path.append(os.getcwd())

from app.db.session import AsyncSessionLocal
from app.models.knowledge import KnowledgeArticle, KnowledgeUpload
from app.models.product import Product


TEST_ARTICLE_TITLES = {"Test Doc v1"}
TEST_UPLOAD_FILENAMES = {"test_v1.csv", "test_v2.csv"}
SEARCH_MARKER_CODE = "SEARCH-V-CODE"


def _short_ids(items: List[str], limit: int = 10) -> str:
    if not items:
        return "-"
    if len(items) <= limit:
        return ", ".join(items)
    head = ", ".join(items[:limit])
    return f"{head}, ... (+{len(items) - limit} more)"


async def cleanup(*, apply: bool, clear_search_marker: bool) -> None:
    async with AsyncSessionLocal() as db:
        article_rows = await db.execute(
            select(KnowledgeArticle).where(KnowledgeArticle.title.in_(TEST_ARTICLE_TITLES))
        )
        articles = list(article_rows.scalars().all())

        upload_rows = await db.execute(
            select(KnowledgeUpload).where(KnowledgeUpload.filename.in_(TEST_UPLOAD_FILENAMES))
        )
        uploads = list(upload_rows.scalars().all())

        marker_rows = await db.execute(
            select(Product.id, Product.sku).where(Product.master_code == SEARCH_MARKER_CODE)
        )
        marker_products = list(marker_rows.all())

        article_ids = [str(item.id) for item in articles]
        upload_ids = [str(item.id) for item in uploads]
        marker_skus = [str(row[1]) for row in marker_products]

        print("Verification artifact scan")
        print(f"- Knowledge articles to remove: {len(article_ids)}")
        print(f"  ids: {_short_ids(article_ids)}")
        print(f"- Knowledge uploads to remove: {len(upload_ids)}")
        print(f"  ids: {_short_ids(upload_ids)}")
        print(f"- Products with SEARCH-V-CODE marker: {len(marker_skus)}")
        print(f"  skus: {_short_ids(marker_skus)}")

        if not apply:
            print("\nDry run only. Re-run with --apply to execute cleanup.")
            return

        for article in articles:
            await db.delete(article)

        for upload in uploads:
            await db.delete(upload)

        if clear_search_marker:
            await db.execute(
                update(Product)
                .where(Product.master_code == SEARCH_MARKER_CODE)
                .values(master_code=Product.sku)
            )

        await db.commit()
        print("\nCleanup applied successfully.")
        if clear_search_marker:
            print("- SEARCH-V-CODE markers reset to each product's SKU.")
        else:
            print("- SEARCH-V-CODE markers were left unchanged.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup artifacts created by verify scripts.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply cleanup. Without this flag, the script runs in dry-run mode.",
    )
    parser.add_argument(
        "--clear-search-marker",
        action="store_true",
        help="Reset products with master_code=SEARCH-V-CODE back to their SKU.",
    )
    args = parser.parse_args()

    asyncio.run(cleanup(apply=args.apply, clear_search_marker=args.clear_search_marker))


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
