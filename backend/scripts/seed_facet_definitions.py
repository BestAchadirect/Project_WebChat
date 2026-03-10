import argparse
import asyncio
import os
import re
import sys
from typing import Dict, Iterable, List, Mapping, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Allow running as a script: `python scripts/seed_facet_definitions.py`
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from app.models.category import Category
from app.models.product_attribute import FacetValueAlias
from app.services.catalog.attribute_sync_service import (
    JEWELRY_TYPE_SYNONYMS,
    MATERIAL_SYNONYMS,
    THREADING_SYNONYMS,
)
from app.services.catalog.attributes_service import eav_service
from app.services.catalog.category_taxonomy_service import category_taxonomy_service


FACET_SETTINGS: Dict[str, Dict[str, object]] = {
    "category": {"tier": "core", "display_order": 10, "is_multivalue": True, "option_cap": 120, "data_type": "string"},
    "material": {"tier": "core", "display_order": 20, "is_multivalue": False, "option_cap": 40, "data_type": "string"},
    "jewelry_type": {"tier": "core", "display_order": 30, "is_multivalue": False, "option_cap": 60, "data_type": "string"},
    "gauge": {"tier": "core", "display_order": 40, "is_multivalue": False, "option_cap": 80, "data_type": "string"},
    "length": {"tier": "core", "display_order": 50, "is_multivalue": False, "option_cap": 120, "data_type": "string"},
    "color": {"tier": "core", "display_order": 60, "is_multivalue": False, "option_cap": 120, "data_type": "string"},
    "size_in_pack": {"tier": "core", "display_order": 70, "is_multivalue": False, "option_cap": 40, "data_type": "string"},
    "crystal_color": {"tier": "secondary", "display_order": 80, "is_multivalue": False, "option_cap": 80, "data_type": "string"},
    "quantity_in_bulk": {"tier": "secondary", "display_order": 90, "is_multivalue": False, "option_cap": 80, "data_type": "string"},
    "cz_color": {"tier": "secondary", "display_order": 100, "is_multivalue": False, "option_cap": 40, "data_type": "string"},
    "size": {"tier": "secondary", "display_order": 110, "is_multivalue": False, "option_cap": 60, "data_type": "string"},
    "outer_diameter": {"tier": "advanced", "display_order": 120, "is_multivalue": False, "option_cap": 40, "data_type": "string"},
    "packing_option": {"tier": "advanced", "display_order": 130, "is_multivalue": False, "option_cap": 20, "data_type": "string"},
    "pincher_size": {"tier": "advanced", "display_order": 140, "is_multivalue": False, "option_cap": 40, "data_type": "string"},
    "height": {"tier": "advanced", "display_order": 150, "is_multivalue": False, "option_cap": 20, "data_type": "string"},
    "design": {"tier": "advanced", "display_order": 160, "is_multivalue": False, "option_cap": 20, "data_type": "string"},
    "threading": {"tier": "advanced", "display_order": 170, "is_multivalue": False, "option_cap": 20, "data_type": "string"},
    "opal_color": {"tier": "advanced", "display_order": 180, "is_multivalue": False, "option_cap": 20, "data_type": "string"},
    "pearl_color": {"tier": "advanced", "display_order": 190, "is_multivalue": False, "option_cap": 20, "data_type": "string"},
    "rack": {"tier": "advanced", "display_order": 200, "is_multivalue": False, "option_cap": 20, "data_type": "string"},
    "ring_size": {"tier": "advanced", "display_order": 210, "is_multivalue": False, "option_cap": 20, "data_type": "string"},
}


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _alias_rows_for_mapping(
    *,
    attribute_id: int,
    mapping: Mapping[str, str],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for raw, canonical in mapping.items():
        raw_norm = _norm(raw)
        canonical_text = str(canonical or "").strip()
        canonical_norm = _norm(canonical_text)
        if not raw_norm or not canonical_text or not canonical_norm:
            continue
        rows.append(
            {
                "attribute_id": attribute_id,
                "raw_value": str(raw).strip(),
                "raw_value_norm": raw_norm,
                "canonical_value": canonical_text,
                "canonical_value_norm": canonical_norm,
                "is_active": True,
            }
        )
    return rows


def _gauge_alias_mapping() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for gauge in range(0, 31):
        canonical = f"{gauge}g"
        mapping[f"{gauge} gauge"] = canonical
        mapping[f"{gauge} g"] = canonical
        mapping[f"{gauge}g"] = canonical
    return mapping


def _category_alias_rows(attribute_id: int, labels: Iterable[str]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for label in labels:
        tokens = category_taxonomy_service.normalize_category_tokens(label)
        if not tokens:
            continue
        for token in tokens:
            norm = _norm(token)
            if not norm:
                continue
            rows.append(
                {
                    "attribute_id": attribute_id,
                    "raw_value": token,
                    "raw_value_norm": norm,
                    "canonical_value": token,
                    "canonical_value_norm": norm,
                    "is_active": True,
                }
            )
    return rows


async def seed_facets(*, dry_run: bool) -> None:
    facet_names = list(FACET_SETTINGS.keys())
    display_names = {name: name.replace("_", " ").title() for name in facet_names}
    data_types = {name: str(FACET_SETTINGS[name].get("data_type") or "string") for name in facet_names}

    async with AsyncSessionLocal() as db:
        definitions = await eav_service.ensure_definitions(
            db,
            facet_names,
            display_names=display_names,
            data_types=data_types,
        )

        for name, cfg in FACET_SETTINGS.items():
            definition = definitions.get(name)
            if not definition:
                continue
            definition.display_name = display_names[name]
            definition.data_type = data_types[name]
            definition.is_enabled = True
            definition.tier = str(cfg.get("tier") or "secondary")
            definition.display_order = int(cfg.get("display_order") or 100)
            definition.is_multivalue = bool(cfg.get("is_multivalue"))
            definition.option_cap = int(cfg["option_cap"]) if cfg.get("option_cap") is not None else None

        await db.flush()

        alias_rows: List[Dict[str, object]] = []
        material_def = definitions.get("material")
        if material_def:
            alias_rows.extend(
                _alias_rows_for_mapping(attribute_id=int(material_def.id), mapping=MATERIAL_SYNONYMS)
            )

        jewelry_type_def = definitions.get("jewelry_type")
        if jewelry_type_def:
            alias_rows.extend(
                _alias_rows_for_mapping(attribute_id=int(jewelry_type_def.id), mapping=JEWELRY_TYPE_SYNONYMS)
            )

        threading_def = definitions.get("threading")
        if threading_def:
            alias_rows.extend(
                _alias_rows_for_mapping(attribute_id=int(threading_def.id), mapping=THREADING_SYNONYMS)
            )

        gauge_def = definitions.get("gauge")
        if gauge_def:
            alias_rows.extend(
                _alias_rows_for_mapping(attribute_id=int(gauge_def.id), mapping=_gauge_alias_mapping())
            )

        category_def = definitions.get("category")
        if category_def:
            labels = (
                await db.execute(
                    select(Category.label)
                    .where(Category.label.isnot(None))
                    .order_by(Category.label.asc())
                )
            ).scalars().all()
            alias_rows.extend(_category_alias_rows(int(category_def.id), labels))

        if alias_rows:
            deduped: Dict[Tuple[int, str], Dict[str, object]] = {}
            for row in alias_rows:
                key = (int(row["attribute_id"]), str(row["raw_value_norm"]))
                deduped[key] = row
            stmt = pg_insert(FacetValueAlias).values(list(deduped.values()))
            stmt = stmt.on_conflict_do_update(
                index_elements=[FacetValueAlias.attribute_id, FacetValueAlias.raw_value_norm],
                set_={
                    "raw_value": stmt.excluded.raw_value,
                    "canonical_value": stmt.excluded.canonical_value,
                    "canonical_value_norm": stmt.excluded.canonical_value_norm,
                    "is_active": stmt.excluded.is_active,
                },
            )
            await db.execute(stmt)

        if dry_run:
            await db.rollback()
            print("Facet definition seed dry-run completed (rollback applied).")
        else:
            await db.commit()
            print("Facet definitions and aliases seeded successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed facet definitions and value aliases.")
    parser.add_argument("--dry-run", action="store_true", help="Run seed and rollback changes.")
    args = parser.parse_args()
    asyncio.run(seed_facets(dry_run=bool(args.dry_run)))


if __name__ == "__main__":
    main()
