import argparse
import asyncio
import json
import os
import sys
from uuid import UUID

# Add backend directory to path so `app.*` imports work when running script directly.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from app.services.imports.klevu_sync_service import klevu_product_sync_service


async def _run(
    *,
    full: bool,
    max_pages: int | None,
    page_size: int,
    rpm: int | None,
    stop_after_pages: int | None,
    resume_run_id: UUID | None,
) -> None:
    async with AsyncSessionLocal() as db:
        if full:
            result = await klevu_product_sync_service.run_full_sync_cli(
                db,
                page_size=page_size,
                max_pages=max_pages,
                requests_per_minute=rpm,
                stop_after_pages=stop_after_pages,
                resume_run_id=resume_run_id,
            )
        else:
            effective_max_pages = max(1, int(max_pages or 10))
            result = await klevu_product_sync_service.sync_recent_products(
                db,
                max_pages=effective_max_pages,
                page_size=page_size,
                requests_per_minute=rpm,
            )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync products from Klevu into local DB.")
    parser.add_argument("--full", action="store_true", help="Run full sync mode with resumable run tracking.")
    parser.add_argument("--resume-run-id", type=UUID, default=None, help="Resume an existing failed/stopped full sync run.")
    parser.add_argument("--max-pages", type=int, default=None, help="Maximum pages to fetch (optional).")
    parser.add_argument("--page-size", type=int, default=100, help="Records per page (max 100).")
    parser.add_argument("--rpm", type=int, default=None, help="Request rate cap per minute (<= 200 recommended).")
    parser.add_argument("--stop-after-pages", type=int, default=None, help="Stop after N pages (for controlled batch windows).")
    args = parser.parse_args()
    asyncio.run(
        _run(
            full=bool(args.full),
            max_pages=args.max_pages,
            page_size=args.page_size,
            rpm=args.rpm,
            stop_after_pages=args.stop_after_pages,
            resume_run_id=args.resume_run_id,
        )
    )


if __name__ == "__main__":
    main()
