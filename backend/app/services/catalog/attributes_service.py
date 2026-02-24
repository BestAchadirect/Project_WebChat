import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import sqlalchemy as sa
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_attribute import AttributeDefinition, ProductAttributeValue


class EAVService:
    """Helpers for reading and writing product EAV attributes."""

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
        names = [self._normalize_name(n) for n in attributes.keys()]
        definitions = await self.ensure_definitions(
            db,
            names,
            display_names=display_names,
            data_types=data_types,
        )
        attr_ids = {name: definitions[name].id for name in names if name in definitions}

        to_delete: List[int] = []
        to_insert: List[Dict[str, Any]] = []

        for name, raw_value in attributes.items():
            norm_name = self._normalize_name(name)
            if norm_name not in attr_ids:
                continue
            serialized = self._serialize_value(raw_value)
            is_empty = serialized is None or (drop_empty and serialized.strip() == "")
            if is_empty:
                to_delete.append(attr_ids[norm_name])
                continue
            to_insert.append(
                {
                    "product_id": product_id,
                    "attribute_id": attr_ids[norm_name],
                    "value": serialized,
                }
            )

        if to_delete:
            await db.execute(
                delete(ProductAttributeValue).where(
                    ProductAttributeValue.product_id == product_id,
                    ProductAttributeValue.attribute_id.in_(to_delete),
                )
            )

        if to_insert:
            stmt = pg_insert(ProductAttributeValue).values(to_insert)
            stmt = stmt.on_conflict_do_update(
                index_elements=["product_id", "attribute_id"],
                set_={"value": stmt.excluded.value},
            )
            await db.execute(stmt)

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
        names = [self._normalize_name(n) for n in attributes.keys()]
        definitions = await self.ensure_definitions(
            db,
            names,
            display_names=display_names,
            data_types=data_types,
        )

        attr_ids_delete: List[int] = []
        value_rows: List[Tuple[int, str]] = []

        for name, raw_value in attributes.items():
            norm_name = self._normalize_name(name)
            definition = definitions.get(norm_name)
            if not definition:
                continue
            attr_id = definition.id
            serialized = self._serialize_value(raw_value)
            is_empty = serialized is None or (drop_empty and serialized.strip() == "")
            if is_empty:
                attr_ids_delete.append(attr_id)
                continue
            value_rows.append((attr_id, serialized))

        if attr_ids_delete:
            await db.execute(
                delete(ProductAttributeValue).where(
                    ProductAttributeValue.product_id.in_(product_ids),
                    ProductAttributeValue.attribute_id.in_(attr_ids_delete),
                )
            )

        if value_rows:
            params: Dict[str, Any] = {
                "product_ids": list(product_ids),
            }
            values_sql_parts: List[str] = []
            for idx, (attr_id, value) in enumerate(value_rows):
                params[f"attr_id_{idx}"] = attr_id
                params[f"val_{idx}"] = value
                values_sql_parts.append(f"(:attr_id_{idx}, :val_{idx})")

            values_sql = ", ".join(values_sql_parts)
            sql = f"""
            INSERT INTO product_attribute_values (product_id, attribute_id, value)
            SELECT pid, attrs.attribute_id, attrs.value
            FROM unnest(:product_ids::uuid[]) AS pid
            CROSS JOIN (VALUES {values_sql}) AS attrs(attribute_id, value)
            ON CONFLICT (product_id, attribute_id) DO UPDATE
            SET value = EXCLUDED.value
            """
            await db.execute(sa.text(sql), params)

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

        deduped: Dict[Tuple[Any, str], Any] = {}
        for product_id, name, value in rows:
            norm_name = self._normalize_name(name)
            if not norm_name or product_id is None:
                continue
            deduped[(product_id, norm_name)] = value

        if not deduped:
            return {"rows_total": len(rows), "unique_pairs": 0, "insert_rows": 0, "drop_empty": 0}

        names = {name for (_pid, name) in deduped.keys()}
        definitions = await self.ensure_definitions(
            db,
            names,
            display_names=display_names,
            data_types=data_types,
        )

        delete_pairs: List[Tuple[Any, int]] = []
        insert_rows: List[Tuple[Any, int, str]] = []
        empty_pairs = 0

        for (product_id, name), raw_value in deduped.items():
            definition = definitions.get(name)
            if not definition:
                continue
            attr_id = definition.id
            serialized = self._serialize_value(raw_value)
            is_empty = serialized is None or (drop_empty and serialized.strip() == "")
            if is_empty:
                empty_pairs += 1
                if drop_empty:
                    delete_pairs.append((product_id, attr_id))
                continue
            insert_rows.append((product_id, attr_id, serialized))

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
            for i in range(0, len(items), size):
                yield items[i : i + size]

        delete_chunk_size = _resolve_chunk_size(len(delete_pairs), params_per_row=2)
        for chunk in _chunks(delete_pairs, delete_chunk_size):
            params: Dict[str, Any] = {}
            values_sql_parts: List[str] = []
            for idx, (product_id, attr_id) in enumerate(chunk):
                params[f"pid_{idx}"] = product_id
                params[f"attr_{idx}"] = attr_id
                values_sql_parts.append(f"(:pid_{idx}, :attr_{idx})")
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
            insert_chunk_size = _resolve_chunk_size(len(insert_rows), params_per_row=3)
            for chunk in _chunks(insert_rows, insert_chunk_size):
                params = {}
                values_sql_parts = []
                for idx, (product_id, attr_id, value) in enumerate(chunk):
                    params[f"pid_{idx}"] = product_id
                    params[f"attr_{idx}"] = attr_id
                    params[f"val_{idx}"] = value
                    values_sql_parts.append(f"(:pid_{idx}, :attr_{idx}, :val_{idx})")
                values_sql = ", ".join(values_sql_parts)
                sql = f"""
                INSERT INTO product_attribute_values (product_id, attribute_id, value)
                VALUES {values_sql}
                ON CONFLICT (product_id, attribute_id) DO UPDATE
                SET value = EXCLUDED.value
                """
                await db.execute(sa.text(sql), params)

        unique_pairs = len(deduped)
        insert_count = len(insert_rows)
        return {
            "rows_total": len(rows),
            "unique_pairs": unique_pairs,
            "insert_rows": insert_count,
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
                ProductAttributeValue.value,
            )
            .join(AttributeDefinition, ProductAttributeValue.attribute_id == AttributeDefinition.id)
            .where(ProductAttributeValue.product_id.in_(product_ids))
        )
        result = await db.execute(stmt)
        rows = result.all()
        payload: Dict[Any, Dict[str, Optional[str]]] = {}
        for product_id, name, value in rows:
            item = payload.setdefault(product_id, {})
            item[str(name)] = value
        return payload


eav_service = EAVService()
