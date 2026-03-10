import argparse
import asyncio
import os
import sys
from typing import Dict, Tuple

from sqlalchemy import func, select

# Allow running as a script: `python scripts/check_category_facet_parity.py`
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from app.models.category import Category, ProductCategory
from app.models.product_attribute import AttributeDefinition, ProductAttributeValue


async def _taxonomy_counts() -> Dict[str, int]:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(
                func.lower(func.btrim(Category.label)).label("norm"),
                func.count(func.distinct(ProductCategory.product_id)).label("cnt"),
            )
            .join(ProductCategory, ProductCategory.category_id == Category.id)
            .where(Category.label.isnot(None))
            .group_by(func.lower(func.btrim(Category.label)))
        )
        rows = (await db.execute(stmt)).all()
    return {str(row.norm): int(row.cnt) for row in rows if row.norm}


async def _eav_counts() -> Dict[str, int]:
    async with AsyncSessionLocal() as db:
        category_def = (
            await db.execute(
                select(AttributeDefinition).where(AttributeDefinition.name == "category")
            )
        ).scalar_one_or_none()
        if not category_def:
            return {}
        stmt = (
            select(
                ProductAttributeValue.value_norm.label("norm"),
                func.count(func.distinct(ProductAttributeValue.product_id)).label("cnt"),
            )
            .where(ProductAttributeValue.attribute_id == category_def.id)
            .where(ProductAttributeValue.value_norm.isnot(None))
            .where(ProductAttributeValue.value_norm != "")
            .group_by(ProductAttributeValue.value_norm)
        )
        rows = (await db.execute(stmt)).all()
    return {str(row.norm): int(row.cnt) for row in rows if row.norm}


def _diff_maps(
    taxonomy: Dict[str, int],
    eav: Dict[str, int],
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    taxonomy_only = {key: taxonomy[key] for key in taxonomy.keys() - eav.keys()}
    eav_only = {key: eav[key] for key in eav.keys() - taxonomy.keys()}
    mismatched = {
        key: (eav.get(key, 0) - taxonomy.get(key, 0))
        for key in taxonomy.keys() & eav.keys()
        if eav.get(key, 0) != taxonomy.get(key, 0)
    }
    return taxonomy_only, eav_only, mismatched


async def run(*, top: int) -> None:
    taxonomy = await _taxonomy_counts()
    eav = await _eav_counts()
    taxonomy_only, eav_only, mismatched = _diff_maps(taxonomy, eav)

    taxonomy_total = sum(taxonomy.values())
    eav_total = sum(eav.values())

    print(f"taxonomy_category_keys={len(taxonomy)}")
    print(f"eav_category_keys={len(eav)}")
    print(f"taxonomy_total_assignments={taxonomy_total}")
    print(f"eav_total_assignments={eav_total}")
    print(f"taxonomy_only_keys={len(taxonomy_only)}")
    print(f"eav_only_keys={len(eav_only)}")
    print(f"mismatched_shared_keys={len(mismatched)}")

    if taxonomy_only:
        print("\nTop taxonomy-only categories:")
        for key, count in sorted(taxonomy_only.items(), key=lambda item: item[1], reverse=True)[:top]:
            print(f"  {key}: {count}")

    if eav_only:
        print("\nTop EAV-only categories:")
        for key, count in sorted(eav_only.items(), key=lambda item: item[1], reverse=True)[:top]:
            print(f"  {key}: {count}")

    if mismatched:
        print("\nTop shared-key count deltas (eav - taxonomy):")
        for key, delta in sorted(mismatched.items(), key=lambda item: abs(item[1]), reverse=True)[:top]:
            print(f"  {key}: {delta}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare taxonomy category counts with EAV category facet counts.")
    parser.add_argument("--top", type=int, default=20, help="Show top N mismatches per section.")
    args = parser.parse_args()
    asyncio.run(run(top=max(1, int(args.top))))


if __name__ == "__main__":
    main()
