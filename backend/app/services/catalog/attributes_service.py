import json
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_attribute import (
    AttributeDefinition,
    FacetValueAlias,
    ProductAttributeValue,
)


class EAVService:
    """Helpers for reading and writing product EAV attributes."""

    _INTERNAL_SEARCH_ATTRIBUTE_NAMES = frozenset({"source_id", "source_raw_sku"})

    def __init__(self) -> None:
        self._searchable_attribute_cache: Tuple[float, Tuple[str, ...]] = (0.0, tuple())

    @staticmethod
    def _normalize_name(name: str) -> str:
        return (name or "").strip()

    @staticmethod
    def _default_display_name(name: str) -> str:
        return name.replace("_", " ").title()

    @staticmethod
    def _serialize_value(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=True)
        return str(value)

    @staticmethod
    def _normalize_value_norm(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        norm = str(value).strip().lower()
        return norm or None

    @classmethod
    def _split_multivalue(cls, value: Any) -> List[Any]:
        items: List[Any] = []

        def _collect(raw: Any) -> None:
            if raw is None:
                return
            if isinstance(raw, (list, tuple, set)):
                for nested in raw:
                    _collect(nested)
                return
            if isinstance(raw, str):
                text = raw.strip()
                if not text:
                    return
                if ";;" in text:
                    for token in text.split(";;"):
                        _collect(token)
                    return
                if ";" in text:
                    for token in text.split(";"):
                        _collect(token)
                    return
            items.append(raw)

        _collect(value)
        return items

    async def get_definitions_by_name(
        self,
        db: AsyncSession,
        names: Sequence[str],
    ) -> Dict[str, AttributeDefinition]:
        cleaned = [self._normalize_name(n) for n in names if self._normalize_name(n)]
        if not cleaned:
            return {}
        stmt = select(AttributeDefinition).where(AttributeDefinition.name.in_(cleaned))
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return {row.name: row for row in rows}

    async def get_searchable_attribute_names(
        self,
        db: AsyncSession,
        *,
        exclude_internal: bool = True,
        ttl_seconds: int = 300,
    ) -> List[str]:
        """Return enabled attributes that currently have at least one catalog value."""
        now = time.time()
        cached_at, cached_names = self._searchable_attribute_cache
        if cached_names and cached_at + max(1, int(ttl_seconds)) > now:
            return list(cached_names)

        exists_values = (
            select(ProductAttributeValue.id)
            .where(ProductAttributeValue.attribute_id == AttributeDefinition.id)
            .limit(1)
            .exists()
        )
        stmt = (
            select(AttributeDefinition.name)
            .where(AttributeDefinition.is_enabled.is_(True))
            .where(exists_values)
            .order_by(AttributeDefinition.display_order.asc(), AttributeDefinition.name.asc())
        )
        rows = list((await db.execute(stmt)).scalars().all() or [])
        names = [
            str(name or "").strip().lower()
            for name in rows
            if str(name or "").strip()
        ]
        if exclude_internal:
            names = [name for name in names if name not in self._INTERNAL_SEARCH_ATTRIBUTE_NAMES]
        deduped = tuple(dict.fromkeys(names))
        self._searchable_attribute_cache = (now, deduped)
        return list(deduped)

    async def ensure_definitions(
        self,
        db: AsyncSession,
        names: Iterable[str],
        *,
        display_names: Optional[Mapping[str, str]] = None,
        data_types: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, AttributeDefinition]:
        normalized = [self._normalize_name(n) for n in names if self._normalize_name(n)]
        existing = await self.get_definitions_by_name(db, normalized)
        missing = [n for n in normalized if n not in existing]
        if missing:
            for name in missing:
                display_name = (display_names or {}).get(name) or self._default_display_name(name)
                data_type = (data_types or {}).get(name) or "string"
                db.add(
                    AttributeDefinition(
                        name=name,
                        display_name=display_name,
                        data_type=data_type,
                    )
                )
            await db.flush()
            existing = await self.get_definitions_by_name(db, normalized)
        return existing

    async def _load_alias_lookup(
        self,
        db: AsyncSession,
        *,
        pairs: Sequence[Tuple[int, str]],
    ) -> Dict[Tuple[int, str], Tuple[str, str]]:
        normalized_pairs = [(int(attr_id), str(norm)) for attr_id, norm in pairs if norm]
        if not normalized_pairs:
            return {}
        attribute_ids = sorted({attr_id for attr_id, _ in normalized_pairs})
        norms = sorted({norm for _, norm in normalized_pairs})
        if not attribute_ids or not norms:
            return {}
        stmt = (
            select(
                FacetValueAlias.attribute_id,
                FacetValueAlias.raw_value_norm,
                FacetValueAlias.canonical_value,
                FacetValueAlias.canonical_value_norm,
            )
            .where(FacetValueAlias.is_active.is_(True))
            .where(FacetValueAlias.attribute_id.in_(attribute_ids))
            .where(FacetValueAlias.raw_value_norm.in_(norms))
        )
        rows = (await db.execute(stmt)).all()
        return {
            (int(row.attribute_id), str(row.raw_value_norm)): (
                str(row.canonical_value),
                str(row.canonical_value_norm),
            )
            for row in rows
            if row.raw_value_norm
        }

    def _canonicalize_value(
        self,
        *,
        attribute_id: int,
        value: str,
        value_norm: Optional[str],
        alias_lookup: Mapping[Tuple[int, str], Tuple[str, str]],
    ) -> Tuple[str, Optional[str]]:
        if not value_norm:
            return value, None
        alias = alias_lookup.get((attribute_id, value_norm))
        if not alias:
            return value, value_norm
        canonical_value, canonical_norm = alias
        cleaned_value = str(canonical_value).strip()
        cleaned_norm = self._normalize_value_norm(canonical_norm)
        if not cleaned_value:
            cleaned_value = value
        return cleaned_value, cleaned_norm or self._normalize_value_norm(cleaned_value)

    async def upsert_product_attributes(
        self,
        db: AsyncSession,
        *,
        product_id: Any,
        attributes: Mapping[str, Any],
        display_names: Optional[Mapping[str, str]] = None,
        data_types: Optional[Mapping[str, str]] = None,
        drop_empty: bool = True,
    ) -> None:
        if not attributes:
            return
        rows: List[Tuple[Any, str, Any]] = [
            (product_id, str(name), value)
            for name, value in attributes.items()
            if self._normalize_name(str(name))
        ]
        await self.bulk_upsert_product_attribute_rows(
            db,
            rows=rows,
            display_names=display_names,
            data_types=data_types,
            drop_empty=drop_empty,
        )

    async def bulk_upsert_product_attributes(
        self,
        db: AsyncSession,
        *,
        product_ids: Sequence[Any],
        attributes: Mapping[str, Any],
        display_names: Optional[Mapping[str, str]] = None,
        data_types: Optional[Mapping[str, str]] = None,
        drop_empty: bool = True,
    ) -> None:
        if not product_ids or not attributes:
            return
        rows: List[Tuple[Any, str, Any]] = []
        for product_id in product_ids:
            for name, value in attributes.items():
                rows.append((product_id, str(name), value))
        await self.bulk_upsert_product_attribute_rows(
            db,
            rows=rows,
            display_names=display_names,
            data_types=data_types,
            drop_empty=drop_empty,
        )

    async def bulk_upsert_product_attribute_rows(
        self,
        db: AsyncSession,
        *,
        rows: Sequence[Tuple[Any, str, Any]],
        display_names: Optional[Mapping[str, str]] = None,
        data_types: Optional[Mapping[str, str]] = None,
        drop_empty: bool = True,
        chunk_size: Optional[int] = None,
    ) -> Dict[str, int]:
        if not rows:
            return {"rows_total": 0, "unique_pairs": 0, "insert_rows": 0, "drop_empty": 0}

        names = [self._normalize_name(str(name)) for (_product_id, name, _value) in rows]
        clean_names = [name for name in names if name]
        if not clean_names:
            return {"rows_total": len(rows), "unique_pairs": 0, "insert_rows": 0, "drop_empty": 0}

        definitions = await self.ensure_definitions(
            db,
            clean_names,
            display_names=display_names,
            data_types=data_types,
        )

        replace_pairs: set[Tuple[Any, int]] = set()
        single_values: Dict[Tuple[Any, int], Tuple[str, Optional[str]]] = {}
        multi_values: Dict[Tuple[Any, int], Dict[str, Tuple[str, Optional[str]]]] = {}
        empty_pairs = 0

        for product_id, raw_name, raw_value in rows:
            name = self._normalize_name(str(raw_name))
            if product_id is None or not name:
                continue
            definition = definitions.get(name)
            if not definition:
                continue
            attr_id = int(definition.id)
            key = (product_id, attr_id)
            replace_pairs.add(key)

            is_multivalue = bool(getattr(definition, "is_multivalue", False)) or name == "category"
            if is_multivalue:
                exploded = self._split_multivalue(raw_value)
                candidates = exploded if exploded else [raw_value]
                bucket = multi_values.setdefault(key, {})
                for item in candidates:
                    serialized = self._serialize_value(item)
                    if serialized is None:
                        empty_pairs += 1
                        continue
                    is_blank = not str(serialized).strip()
                    if is_blank and drop_empty:
                        empty_pairs += 1
                        continue
                    value_norm = self._normalize_value_norm(serialized)
                    dedupe_key = value_norm or f"__raw__:{serialized}"
                    bucket[dedupe_key] = (serialized, value_norm)
            else:
                serialized = self._serialize_value(raw_value)
                if serialized is None:
                    empty_pairs += 1
                    continue
                is_blank = not str(serialized).strip()
                if is_blank and drop_empty:
                    empty_pairs += 1
                    continue
                single_values[key] = (serialized, self._normalize_value_norm(serialized))

        alias_candidates: List[Tuple[int, str]] = []
        for (_product_id, attr_id), (_value, value_norm) in single_values.items():
            if value_norm:
                alias_candidates.append((attr_id, value_norm))
        for (_product_id, attr_id), bucket in multi_values.items():
            for _dedupe_key, (_value, value_norm) in bucket.items():
                if value_norm:
                    alias_candidates.append((attr_id, value_norm))
        alias_lookup = await self._load_alias_lookup(db, pairs=alias_candidates)

        insert_rows: List[Tuple[Any, int, str, Optional[str]]] = []
        for (product_id, attr_id), (value, value_norm) in single_values.items():
            canonical_value, canonical_norm = self._canonicalize_value(
                attribute_id=attr_id,
                value=value,
                value_norm=value_norm,
                alias_lookup=alias_lookup,
            )
            insert_rows.append((product_id, attr_id, canonical_value, canonical_norm))

        for (product_id, attr_id), bucket in multi_values.items():
            deduped_bucket: Dict[str, Tuple[str, Optional[str]]] = {}
            for dedupe_key, (value, value_norm) in bucket.items():
                canonical_value, canonical_norm = self._canonicalize_value(
                    attribute_id=attr_id,
                    value=value,
                    value_norm=value_norm,
                    alias_lookup=alias_lookup,
                )
                canonical_key = canonical_norm or dedupe_key
                deduped_bucket[canonical_key] = (canonical_value, canonical_norm)
            for _key, (canonical_value, canonical_norm) in deduped_bucket.items():
                insert_rows.append((product_id, attr_id, canonical_value, canonical_norm))

        def _resolve_chunk_size(total: int, params_per_row: int) -> int:
            if chunk_size and chunk_size > 0:
                return chunk_size
            if total < 1_000:
                base = 300
            elif total < 10_000:
                base = 800
            else:
                base = 1_500
            max_params = 60_000
            safe = max(1, max_params // max(1, params_per_row))
            return min(base, safe)

        def _chunks(items: List[Any], size: int) -> Iterable[List[Any]]:
            for index in range(0, len(items), size):
                yield items[index : index + size]

        replace_pairs_list = list(replace_pairs)
        if replace_pairs_list:
            delete_chunk_size = _resolve_chunk_size(len(replace_pairs_list), params_per_row=2)
            for chunk in _chunks(replace_pairs_list, delete_chunk_size):
                params: Dict[str, Any] = {}
                values_sql_parts: List[str] = []
                for idx, (product_id, attr_id) in enumerate(chunk):
                    params[f"pid_{idx}"] = product_id
                    params[f"attr_{idx}"] = attr_id
                    values_sql_parts.append(
                        f"(CAST(:pid_{idx} AS uuid), CAST(:attr_{idx} AS bigint))"
                    )
                values_sql = ", ".join(values_sql_parts)
                sql = f"""
                WITH pairs(product_id, attribute_id) AS (
                    VALUES {values_sql}
                )
                DELETE FROM product_attribute_values pav
                USING pairs
                WHERE pav.product_id = pairs.product_id
                  AND pav.attribute_id = pairs.attribute_id
                """
                await db.execute(sa.text(sql), params)

        if insert_rows:
            insert_chunk_size = _resolve_chunk_size(len(insert_rows), params_per_row=4)
            for chunk in _chunks(insert_rows, insert_chunk_size):
                params: Dict[str, Any] = {}
                values_sql_parts: List[str] = []
                for idx, (product_id, attr_id, value, value_norm) in enumerate(chunk):
                    params[f"pid_{idx}"] = product_id
                    params[f"attr_{idx}"] = attr_id
                    params[f"val_{idx}"] = value
                    params[f"norm_{idx}"] = value_norm
                    values_sql_parts.append(
                        "(CAST(:pid_{idx} AS uuid), CAST(:attr_{idx} AS bigint), "
                        "CAST(:val_{idx} AS text), CAST(:norm_{idx} AS text))".format(idx=idx)
                    )
                values_sql = ", ".join(values_sql_parts)
                sql = f"""
                INSERT INTO product_attribute_values (product_id, attribute_id, value, value_norm)
                VALUES {values_sql}
                ON CONFLICT (product_id, attribute_id, value_norm)
                WHERE value_norm IS NOT NULL AND value_norm <> ''
                DO UPDATE SET
                    value = EXCLUDED.value,
                    value_norm = EXCLUDED.value_norm
                """
                await db.execute(sa.text(sql), params)

        return {
            "rows_total": len(rows),
            "unique_pairs": len(replace_pairs),
            "insert_rows": len(insert_rows),
            "drop_empty": empty_pairs,
        }

    async def get_product_attributes(
        self,
        db: AsyncSession,
        product_ids: Sequence[Any],
    ) -> Dict[Any, Dict[str, Optional[str]]]:
        if not product_ids:
            return {}
        stmt = (
            select(
                ProductAttributeValue.product_id,
                AttributeDefinition.name,
                AttributeDefinition.is_multivalue,
                ProductAttributeValue.value,
                ProductAttributeValue.value_norm,
                ProductAttributeValue.id,
            )
            .join(AttributeDefinition, ProductAttributeValue.attribute_id == AttributeDefinition.id)
            .where(ProductAttributeValue.product_id.in_(product_ids))
            .order_by(
                ProductAttributeValue.product_id.asc(),
                AttributeDefinition.name.asc(),
                ProductAttributeValue.value_norm.asc().nulls_last(),
                ProductAttributeValue.id.asc(),
            )
        )
        rows = (await db.execute(stmt)).all()
        payload: Dict[Any, Dict[str, Optional[str]]] = {}
        multi_values: Dict[Tuple[Any, str], List[str]] = {}
        multi_seen: Dict[Tuple[Any, str], set[str]] = {}
        for product_id, name, is_multivalue, value, value_norm, _row_id in rows:
            item = payload.setdefault(product_id, {})
            key_name = str(name)
            if bool(is_multivalue):
                if value is None or not str(value).strip():
                    continue
                bucket_key = (product_id, key_name)
                seen = multi_seen.setdefault(bucket_key, set())
                dedupe_key = str(value_norm or self._normalize_value_norm(str(value)) or f"raw:{value}")
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                multi_values.setdefault(bucket_key, []).append(str(value))
                continue
            if key_name not in item:
                item[key_name] = value
        for (product_id, key_name), values in multi_values.items():
            if not values:
                continue
            payload.setdefault(product_id, {})[key_name] = ";;".join(values)
        return payload


eav_service = EAVService()
