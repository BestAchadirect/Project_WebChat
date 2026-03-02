from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.core.config import settings
from app.db.session import AsyncSessionLocal


async def run(*, model: str, apply_changes: bool) -> int:
    async with AsyncSessionLocal() as db:
        total_before = int((await db.execute(text("SELECT COUNT(*) FROM product_embeddings"))).scalar() or 0)
        null_before = int(
            (await db.execute(text("SELECT COUNT(*) FROM product_embeddings WHERE model IS NULL"))).scalar() or 0
        )

        print(f"configured_model={model}")
        print(f"rows_total_before={total_before}")
        print(f"rows_null_model_before={null_before}")

        if not apply_changes:
            print("dry_run=true (no changes applied)")
            return 0

        # Remove duplicate NULL-model rows where target-model row already exists for the same product.
        delete_sql = text(
            """
            DELETE FROM product_embeddings pe_null
            USING product_embeddings pe_target
            WHERE pe_null.product_id = pe_target.product_id
              AND pe_null.model IS NULL
              AND pe_target.model = :model
            """
        )
        delete_result = await db.execute(delete_sql, {"model": model})
        deleted = int(delete_result.rowcount or 0)

        # Promote remaining NULL-model rows to the configured model.
        update_sql = text("UPDATE product_embeddings SET model = :model WHERE model IS NULL")
        update_result = await db.execute(update_sql, {"model": model})
        updated = int(update_result.rowcount or 0)

        await db.commit()

        total_after = int((await db.execute(text("SELECT COUNT(*) FROM product_embeddings"))).scalar() or 0)
        null_after = int(
            (await db.execute(text("SELECT COUNT(*) FROM product_embeddings WHERE model IS NULL"))).scalar() or 0
        )
        model_after = int(
            (await db.execute(text("SELECT COUNT(*) FROM product_embeddings WHERE model = :model"), {"model": model})).scalar()
            or 0
        )

        print(f"rows_deleted_duplicates={deleted}")
        print(f"rows_updated_from_null={updated}")
        print(f"rows_total_after={total_after}")
        print(f"rows_null_model_after={null_after}")
        print(f"rows_model_after={model_after}")
        print("done=true")
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill legacy NULL product embedding model rows to a configured model."
    )
    parser.add_argument(
        "--model",
        default=str(getattr(settings, "PRODUCT_EMBEDDING_MODEL", "") or "").strip(),
        help="Target embedding model label (default: PRODUCT_EMBEDDING_MODEL).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag, runs as dry-run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = str(args.model or "").strip()
    if not model:
        raise SystemExit("Missing --model and PRODUCT_EMBEDDING_MODEL is empty.")
    asyncio.run(run(model=model, apply_changes=bool(args.apply)))


if __name__ == "__main__":
    main()
