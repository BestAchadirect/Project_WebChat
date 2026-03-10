from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence
from uuid import UUID

from sqlalchemy import delete, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductEmbedding
from app.models.product_attribute import ProductAttributeValue
from app.models.product_change import ProductChange
from app.models.product_group import ProductGroup
from app.models.product_search_projection import ProductSearchProjection
from app.services.catalog.attribute_sync_service import product_attribute_sync_service

from .types import KlevuSyncStats, PageLookupContext, ProductResolution


class KlevuResolutionMixin:
    async def _ensure_group(self, db: AsyncSession, *, master_code: str, cache: Dict[str, UUID]) -> UUID:
        cached = cache.get(master_code)
        if cached:
            return cached
        result = await db.execute(select(ProductGroup).where(ProductGroup.master_code == master_code))
        group = result.scalar_one_or_none()
        if group is None:
            group = ProductGroup(master_code=master_code)
            db.add(group)
            await db.flush()
        cache[master_code] = group.id
        return group.id

    async def _preload_groups(
        self,
        db: AsyncSession,
        *,
        master_codes: Sequence[str],
        cache: Dict[str, UUID],
    ) -> None:
        missing = sorted({code for code in master_codes if code and code not in cache})
        if not missing:
            return
        result = await db.execute(select(ProductGroup).where(ProductGroup.master_code.in_(missing)))
        for group in result.scalars().all():
            cache[group.master_code] = group.id

    @staticmethod
    def _append_lookup_entry(mapping: Dict[str, List[Product]], key: Optional[str], product: Product) -> None:
        normalized = str(key or "").strip()
        if not normalized:
            return
        bucket = mapping.setdefault(normalized, [])
        if any(item.id == product.id for item in bucket):
            return
        bucket.append(product)

    @staticmethod
    def _remove_lookup_entry(mapping: Dict[str, List[Product]], key: Optional[str], product_id: UUID) -> None:
        normalized = str(key or "").strip()
        if not normalized:
            return
        bucket = mapping.get(normalized)
        if not bucket:
            return
        mapping[normalized] = [item for item in bucket if item.id != product_id]
        if not mapping[normalized]:
            mapping.pop(normalized, None)

    def _register_product_lookup(self, context: PageLookupContext, product: Product) -> None:
        self._append_lookup_entry(context.products_by_sku, product.sku, product)
        self._append_lookup_entry(context.products_by_object_id, product.object_id, product)
        self._append_lookup_entry(context.products_by_klevu_id, product.klevu_id, product)

    def _remove_product_lookup(
        self,
        context: PageLookupContext,
        *,
        product_id: UUID,
        sku: Optional[str],
        object_id: Optional[str],
        klevu_id: Optional[str],
    ) -> None:
        self._remove_lookup_entry(context.products_by_sku, sku, product_id)
        self._remove_lookup_entry(context.products_by_object_id, object_id, product_id)
        self._remove_lookup_entry(context.products_by_klevu_id, klevu_id, product_id)

    async def _build_page_lookup_context(
        self,
        db: AsyncSession,
        *,
        payloads: Sequence[Mapping[str, Any]],
    ) -> PageLookupContext:
        sku_terms: set[str] = set()
        object_ids: set[str] = set()
        klevu_ids: set[str] = set()
        for payload in payloads:
            sku = self._clean_text(payload.get("sku"))
            raw_sku = self._clean_text(payload.get("raw_sku"))
            object_id = self._clean_text(payload.get("object_id"))
            klevu_id = self._clean_text(payload.get("klevu_id"))
            if sku:
                sku_terms.add(sku)
            if raw_sku:
                sku_terms.add(raw_sku)
            if object_id:
                object_ids.add(object_id)
            if klevu_id:
                klevu_ids.add(klevu_id)

        if not sku_terms and not object_ids and not klevu_ids:
            return PageLookupContext(products_by_sku={}, products_by_object_id={}, products_by_klevu_id={})

        clauses = []
        if sku_terms:
            clauses.append(Product.sku.in_(list(sku_terms)))
        if object_ids:
            clauses.append(Product.object_id.in_(list(object_ids)))
        if klevu_ids:
            clauses.append(Product.klevu_id.in_(list(klevu_ids)))
        stmt = select(Product).where(or_(*clauses))

        result = await db.execute(stmt)
        context = PageLookupContext(products_by_sku={}, products_by_object_id={}, products_by_klevu_id={})
        for product in result.scalars().all():
            self._register_product_lookup(context, product)
        return context

    def _resolve_existing_product_from_lookup(
        self,
        *,
        payload: Mapping[str, Any],
        lookup_context: PageLookupContext,
    ) -> ProductResolution:
        canonical_sku = self._clean_text(payload.get("sku"))
        raw_sku = self._clean_text(payload.get("raw_sku"))
        object_id = self._clean_text(payload.get("object_id"))
        klevu_id = self._clean_text(payload.get("klevu_id"))

        candidates: List[Product] = []
        for key in (canonical_sku, raw_sku):
            if key:
                candidates.extend(lookup_context.products_by_sku.get(key, []))
        if object_id:
            candidates.extend(lookup_context.products_by_object_id.get(object_id, []))
        if klevu_id:
            candidates.extend(lookup_context.products_by_klevu_id.get(klevu_id, []))

        deduped: List[Product] = []
        seen_ids: set[UUID] = set()
        for item in candidates:
            if item.id in seen_ids:
                continue
            seen_ids.add(item.id)
            deduped.append(item)
        if not deduped:
            return ProductResolution(selected=None, duplicates=[])

        canonical_match = next((item for item in deduped if item.sku == canonical_sku), None)
        raw_match = next((item for item in deduped if raw_sku and item.sku == raw_sku), None)
        object_match = next((item for item in deduped if object_id and item.object_id == object_id), None)
        klevu_match = next((item for item in deduped if klevu_id and item.klevu_id == klevu_id), None)
        selected = canonical_match or klevu_match or raw_match or object_match
        if selected is None:
            selected = sorted(
                deduped,
                key=lambda item: (item.updated_at or datetime.min, item.created_at or datetime.min),
                reverse=True,
            )[0]
        duplicates = [item for item in deduped if item.id != selected.id]
        return ProductResolution(selected=selected, duplicates=duplicates)

    async def _resolve_existing_product(self, db: AsyncSession, payload: Mapping[str, Any]) -> ProductResolution:
        clauses = [Product.sku == payload["sku"]]
        raw_sku = payload.get("raw_sku")
        if raw_sku and raw_sku != payload["sku"]:
            clauses.append(Product.sku == raw_sku)
        object_id = payload.get("object_id")
        if object_id:
            clauses.append(Product.object_id == object_id)
        klevu_id = payload.get("klevu_id")
        if klevu_id:
            clauses.append(Product.klevu_id == klevu_id)

        stmt = (
            select(Product)
            .where(or_(*clauses))
            .order_by(desc(Product.updated_at), desc(Product.created_at))
        )
        result = await db.execute(stmt)
        matches = list(result.scalars().all())
        if not matches:
            return ProductResolution(selected=None, duplicates=[])

        canonical_match = next((item for item in matches if item.sku == payload["sku"]), None)
        raw_match = next((item for item in matches if raw_sku and item.sku == raw_sku), None)
        object_match = next((item for item in matches if object_id and item.object_id == object_id), None)
        klevu_match = next((item for item in matches if klevu_id and item.klevu_id == klevu_id), None)
        selected = canonical_match or klevu_match or raw_match or object_match or matches[0]

        duplicates: List[Product] = []
        for item in matches:
            if item.id == selected.id:
                continue
            duplicates.append(item)
        return ProductResolution(selected=selected, duplicates=duplicates)

    async def _delete_duplicate_product(self, db: AsyncSession, *, product_id: UUID) -> None:
        await db.execute(delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id))
        await db.execute(delete(ProductAttributeValue).where(ProductAttributeValue.product_id == product_id))
        await db.execute(delete(ProductChange).where(ProductChange.product_id == product_id))
        await db.execute(delete(ProductSearchProjection).where(ProductSearchProjection.product_id == product_id))
        await db.execute(delete(Product).where(Product.id == product_id))

    async def _merge_and_cleanup_duplicates(
        self,
        db: AsyncSession,
        *,
        selected: Product,
        duplicates: Sequence[Product],
        payload: Mapping[str, Any],
        stats: KlevuSyncStats,
        lookup_context: Optional[PageLookupContext] = None,
    ) -> None:
        for duplicate in duplicates:
            if duplicate.id == selected.id:
                continue
            duplicate_sku = duplicate.sku
            duplicate_object_id = duplicate.object_id
            merged_legacy = list(selected.legacy_sku or [])
            for token in (duplicate.legacy_sku or []):
                if token and token not in merged_legacy and token != selected.sku:
                    merged_legacy.append(token)
            if duplicate.sku and duplicate.sku != selected.sku and duplicate.sku not in merged_legacy:
                merged_legacy.append(duplicate.sku)
            selected.legacy_sku = merged_legacy

            if not selected.object_id and duplicate.object_id:
                selected.object_id = duplicate.object_id
            if not selected.klevu_id and duplicate.klevu_id:
                selected.klevu_id = duplicate.klevu_id
            if not selected.description and duplicate.description:
                selected.description = duplicate.description
            if not selected.image_url and duplicate.image_url:
                selected.image_url = duplicate.image_url
            if not selected.product_url and duplicate.product_url:
                selected.product_url = duplicate.product_url

            selected.attributes = product_attribute_sync_service.merge_attributes(
                current=selected.attributes or {},
                updates=duplicate.attributes or {},
                drop_empty=False,
            )
            await self._delete_duplicate_product(db, product_id=duplicate.id)
            if lookup_context is not None:
                self._remove_product_lookup(
                    lookup_context,
                    product_id=duplicate.id,
                    sku=duplicate_sku,
                    object_id=duplicate_object_id,
                    klevu_id=duplicate.klevu_id,
                )
            stats.deduped_legacy_rows += 1

