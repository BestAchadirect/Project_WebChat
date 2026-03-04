from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category, ProductCategory


class CategoryTaxonomyService:
    _CANONICAL_MAP = {
        "silicon": "Silicone",
        "ear piercing others": "Ear Piercing Others",
    }

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).replace("\x00", " ").strip()
        return re.sub(r"\s+", " ", text)

    @classmethod
    def _canonical_label(cls, value: str) -> str:
        lowered = value.strip().lower()
        return cls._CANONICAL_MAP.get(lowered, value.strip())

    @classmethod
    def slugify(cls, label: str) -> str:
        normalized = cls._clean_text(label).lower()
        normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
        normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
        return normalized or "uncategorized"

    @classmethod
    def normalize_category_tokens(cls, raw: Any) -> List[str]:
        if raw is None:
            return []

        chunks: List[str] = []

        def _collect(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    _collect(item)
                return
            text = cls._clean_text(value)
            if not text:
                return
            if ";;" in text:
                for part in text.split(";;"):
                    _collect(part)
                return
            if ";" in text:
                for part in text.split(";"):
                    _collect(part)
                return
            chunks.append(text)

        _collect(raw)

        seen: set[str] = set()
        tokens: List[str] = []
        for chunk in chunks:
            lowered = chunk.lower()
            if lowered == "klevu_product" or "@ku@" in lowered:
                continue
            canonical = cls._canonical_label(chunk)
            key = canonical.lower()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(canonical)
        return tokens

    @classmethod
    def normalize_category_string(cls, raw: Any) -> Optional[str]:
        tokens = cls.normalize_category_tokens(raw)
        return ";;".join(tokens) if tokens else None

    async def ensure_categories(
        self,
        db: AsyncSession,
        *,
        labels: Sequence[str],
        cache: Optional[Dict[str, int]] = None,
    ) -> Dict[str, int]:
        cleaned = [self._clean_text(label) for label in labels if self._clean_text(label)]
        if not cleaned:
            return {}

        slug_to_label: Dict[str, str] = {}
        for label in cleaned:
            slug = self.slugify(label)
            if slug not in slug_to_label:
                slug_to_label[slug] = label

        cache_ref = cache if cache is not None else {}
        missing_slugs = [slug for slug in slug_to_label.keys() if slug not in cache_ref]
        if missing_slugs:
            existing_rows = (
                await db.execute(select(Category.id, Category.slug).where(Category.slug.in_(missing_slugs)))
            ).all()
            for row in existing_rows:
                cache_ref[row.slug] = int(row.id)

        pending_slugs = [slug for slug in missing_slugs if slug not in cache_ref]
        if pending_slugs:
            rows = [{"slug": slug, "label": slug_to_label[slug]} for slug in pending_slugs]
            stmt = pg_insert(Category).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=[Category.slug])
            await db.execute(stmt)

            inserted_rows = (
                await db.execute(select(Category.id, Category.slug).where(Category.slug.in_(pending_slugs)))
            ).all()
            for row in inserted_rows:
                cache_ref[row.slug] = int(row.id)

        return {label: cache_ref[self.slugify(label)] for label in cleaned if self.slugify(label) in cache_ref}

    async def sync_product_categories(
        self,
        db: AsyncSession,
        *,
        product_id: UUID,
        raw_category: Any,
        source: str = "klevu",
        category_cache: Optional[Dict[str, int]] = None,
        clear_when_empty: bool = True,
    ) -> List[str]:
        tokens = self.normalize_category_tokens(raw_category)
        if not tokens:
            if clear_when_empty:
                await db.execute(delete(ProductCategory).where(ProductCategory.product_id == product_id))
            return []

        label_to_id = await self.ensure_categories(db, labels=tokens, cache=category_cache)
        ordered_category_ids: List[int] = []
        seen: set[int] = set()
        for token in tokens:
            category_id = label_to_id.get(token)
            if category_id is None or category_id in seen:
                continue
            seen.add(category_id)
            ordered_category_ids.append(category_id)

        if not ordered_category_ids:
            return []

        existing_ids = set(
            (
                await db.execute(
                    select(ProductCategory.category_id).where(ProductCategory.product_id == product_id)
                )
            ).scalars().all()
        )
        target_ids = set(ordered_category_ids)

        stale_ids = sorted(existing_ids - target_ids)
        if stale_ids:
            await db.execute(
                delete(ProductCategory).where(
                    ProductCategory.product_id == product_id,
                    ProductCategory.category_id.in_(stale_ids),
                )
            )

        rows: List[Mapping[str, Any]] = []
        for index, category_id in enumerate(ordered_category_ids):
            rows.append(
                {
                    "product_id": product_id,
                    "category_id": category_id,
                    "source": source,
                    "is_primary": index == 0,
                }
            )

        stmt = pg_insert(ProductCategory).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProductCategory.product_id, ProductCategory.category_id],
            set_={
                "source": stmt.excluded.source,
                "is_primary": stmt.excluded.is_primary,
            },
        )
        await db.execute(stmt)
        return tokens


category_taxonomy_service = CategoryTaxonomyService()
