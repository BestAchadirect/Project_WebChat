from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.klevu_sync import KlevuSyncFailure
from app.models.product import Product
from app.services.catalog.attributes_service import eav_service
from app.services.catalog.attribute_sync_service import ATTRIBUTE_FIELDS, product_attribute_sync_service
from app.services.catalog.category_taxonomy_service import category_taxonomy_service
from app.services.catalog.projection_service import product_projection_sync_service

from .types import KlevuSyncStats, PageLookupContext

logger = get_logger(__name__)


class KlevuUpsertMixin:
    def _build_search_payload(
        self,
        *,
        product: Product,
    ) -> Dict[str, Any]:
        return product_attribute_sync_service.build_search_document(
            display_name=product.master_code or product.sku,
            sku=product.sku,
            object_id=product.object_id,
            description=product.description,
            legacy_skus=list(product.legacy_sku or []),
            attributes=dict(product.attributes or {}),
            manual_keywords=[],
            attribute_columns=ATTRIBUTE_FIELDS,
        )

    async def _upsert_payload(
        self,
        db: AsyncSession,
        *,
        payload: Mapping[str, Any],
        group_cache: Dict[str, UUID],
        stats: KlevuSyncStats,
        lookup_context: Optional[PageLookupContext] = None,
        pending_eav_rows: Optional[List[tuple[UUID, str, Any]]] = None,
        pending_category_updates: Optional[List[tuple[UUID, Any]]] = None,
    ) -> tuple[str, UUID]:
        if lookup_context is not None:
            resolution = self._resolve_existing_product_from_lookup(
                payload=payload,
                lookup_context=lookup_context,
            )
        else:
            resolution = await self._resolve_existing_product(db, payload)
        product = resolution.selected
        bulk_eav_enabled = bool(getattr(settings, "KLEVU_SYNC_BULK_EAV_ENABLED", True))
        incoming_attributes = dict(payload.get("attributes") or {})
        action = "updated" if product is not None else "created"
        previous_sku = product.sku if product is not None else None
        previous_klevu_id = product.klevu_id if product is not None else None
        previous_object_id = product.object_id if product is not None else None

        group_id = await self._ensure_group(db, master_code=payload["master_code"], cache=group_cache)
        if product is None:
            target_object_id = self._resolve_object_id_for_upsert(
                current_object_id=None,
                incoming_object_id=payload.get("object_id"),
                incoming_klevu_id=payload.get("klevu_id"),
            )
            product = Product(
                sku=payload["sku"],
                master_code=payload["master_code"],
                group_id=group_id,
                price=float(payload.get("price") or 0.0),
                currency=(payload.get("currency") or "USD").upper(),
                description=payload.get("description"),
                stock_status=payload.get("stock_status") or "in_stock",
                stock_qty=payload.get("stock_qty"),
                image_url=payload.get("image_url"),
                product_url=payload.get("product_url"),
                klevu_id=payload.get("klevu_id"),
                object_id=target_object_id,
                visibility=True if payload.get("visibility") is None else bool(payload.get("visibility")),
                is_featured=False if payload.get("is_featured") is None else bool(payload.get("is_featured")),
                priority=int(payload.get("priority") or 0),
                attributes={},
                legacy_sku=list(payload.get("legacy_sku") or []),
                last_stock_sync_at=self._now_utc(),
            )
            db.add(product)
            await db.flush()
            previous_sku = None
            previous_klevu_id = None
            previous_object_id = None
            current_attributes = {}
            merged_attributes = product_attribute_sync_service.merge_attributes(
                current=current_attributes,
                updates=incoming_attributes,
                drop_empty=False,
            )
            attributes_changed = bool(incoming_attributes)
            initial_category_value = None
        else:
            current_attributes = dict(product.attributes or {})
            merged_attributes = product_attribute_sync_service.merge_attributes(
                current=current_attributes,
                updates=incoming_attributes,
                drop_empty=False,
            )
            attributes_changed = merged_attributes != current_attributes
            initial_category_value = current_attributes.get("category")

            target_price = (
                float(payload.get("price") or 0.0)
                if payload.get("price") is not None
                else float(product.price or 0.0)
            )
            target_currency = (payload.get("currency") or product.currency or "USD").upper()
            target_description = payload["description"] if payload.get("description") else product.description
            target_stock_status = payload.get("stock_status") or product.stock_status
            target_stock_qty = payload.get("stock_qty")
            target_image_url = payload["image_url"] if payload.get("image_url") else product.image_url
            target_product_url = payload["product_url"] if payload.get("product_url") else product.product_url
            target_object_id = self._resolve_object_id_for_upsert(
                current_object_id=product.object_id,
                incoming_object_id=payload.get("object_id"),
                incoming_klevu_id=payload.get("klevu_id"),
            )
            target_klevu_id = payload["klevu_id"] if payload.get("klevu_id") else product.klevu_id
            target_visibility = (
                bool(payload["visibility"]) if payload.get("visibility") is not None else bool(product.visibility)
            )
            target_is_featured = (
                bool(payload["is_featured"])
                if payload.get("is_featured") is not None
                else bool(product.is_featured)
            )
            target_priority = (
                int(payload["priority"]) if payload.get("priority") is not None else int(product.priority or 0)
            )

            legacy_tokens = list(product.legacy_sku or [])
            if previous_sku and previous_sku != payload["sku"] and previous_sku not in legacy_tokens:
                legacy_tokens.append(previous_sku)
            for token in list(payload.get("legacy_sku") or []):
                if token and token not in legacy_tokens and token != payload["sku"]:
                    legacy_tokens.append(token)

            current_stock_status = (
                str(product.stock_status.value)
                if hasattr(product.stock_status, "value")
                else str(product.stock_status or "")
            )
            next_stock_status = (
                str(target_stock_status.value)
                if hasattr(target_stock_status, "value")
                else str(target_stock_status or "")
            )
            row_changed = any(
                (
                    product.sku != payload["sku"],
                    product.master_code != payload["master_code"],
                    product.group_id != group_id,
                    abs(float(product.price or 0.0) - float(target_price)) > 1e-9,
                    (product.currency or "").upper() != target_currency,
                    product.description != target_description,
                    current_stock_status != next_stock_status,
                    product.stock_qty != target_stock_qty,
                    product.image_url != target_image_url,
                    product.product_url != target_product_url,
                    product.object_id != target_object_id,
                    product.klevu_id != target_klevu_id,
                    bool(product.visibility) != target_visibility,
                    bool(product.is_featured) != target_is_featured,
                    int(product.priority or 0) != target_priority,
                    list(product.legacy_sku or []) != legacy_tokens,
                    attributes_changed,
                )
            )
            if not row_changed and not resolution.duplicates:
                return "unchanged", product.id

            product.sku = payload["sku"]
            product.master_code = payload["master_code"]
            product.group_id = group_id
            product.price = float(target_price)
            product.currency = target_currency
            product.description = target_description
            product.stock_status = target_stock_status
            product.stock_qty = target_stock_qty
            product.image_url = target_image_url
            product.product_url = target_product_url
            product.object_id = target_object_id
            product.klevu_id = target_klevu_id
            product.visibility = target_visibility
            product.is_featured = target_is_featured
            product.priority = target_priority
            product.legacy_sku = legacy_tokens
            product.last_stock_sync_at = self._now_utc()

        attributes_touched = False
        if incoming_attributes:
            if bulk_eav_enabled and pending_eav_rows is not None:
                if action == "created" or attributes_changed:
                    product.attributes = merged_attributes
                    attributes_touched = True
            else:
                if action == "created" or attributes_changed:
                    await product_attribute_sync_service.apply_dual_canonical(
                        db=db,
                        product=product,
                        attribute_updates=incoming_attributes,
                        drop_empty=False,
                    )
                    attributes_touched = True

        await self._merge_and_cleanup_duplicates(
            db,
            selected=product,
            duplicates=resolution.duplicates,
            payload=payload,
            stats=stats,
            lookup_context=lookup_context,
        )
        final_category_value = (product.attributes or {}).get("category")
        category_changed = final_category_value != initial_category_value
        if not bool(getattr(settings, "KLEVU_SYNC_DEFER_SEARCH_TEXT", False)):
            search_payload = self._build_search_payload(product=product)
            search_changed = any(
                (
                    (product.search_text or "") != str(search_payload.get("search_text") or ""),
                    (product.search_hash or "") != str(search_payload.get("search_hash") or ""),
                    list(product.search_keywords or []) != list(search_payload.get("search_keywords") or []),
                )
            )
            if search_changed:
                product.search_text = search_payload["search_text"]
                product.search_hash = search_payload["search_hash"]
                product.search_keywords = search_payload["search_keywords"]

        await db.flush()
        if lookup_context is not None:
            self._remove_product_lookup(
                lookup_context,
                product_id=product.id,
                sku=previous_sku,
                object_id=previous_object_id,
                klevu_id=previous_klevu_id,
            )
            self._register_product_lookup(lookup_context, product)
        if (
            bulk_eav_enabled
            and pending_eav_rows is not None
            and (action == "created" or attributes_touched or resolution.duplicates)
        ):
            for key, value in (product.attributes or {}).items():
                pending_eav_rows.append((product.id, str(key), value))
        if (
            bool(getattr(settings, "FACETS_V2_DUAL_WRITE_ENABLED", True))
            and pending_category_updates is not None
            and (action == "created" or category_changed or resolution.duplicates)
        ):
            pending_category_updates.append((product.id, (product.attributes or {}).get("category")))
        return action, product.id

    async def _record_failure(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        page_offset: int,
        payload: Optional[Mapping[str, Any]],
        record: Mapping[str, Any],
        error: Exception,
    ) -> None:
        failure = KlevuSyncFailure(
            run_id=run_id,
            page_offset=page_offset,
            raw_sku=(payload or {}).get("raw_sku"),
            canonical_sku=(payload or {}).get("sku"),
            error_type=error.__class__.__name__,
            error_message=str(error)[:2000],
            record_payload=self._to_jsonable(record),
        )
        db.add(failure)
        await db.flush()

    async def _process_page_rows(
        self,
        db: AsyncSession,
        *,
        records: Sequence[Mapping[str, Any]],
        stats: KlevuSyncStats,
        group_cache: Dict[str, UUID],
        run_id: UUID | None,
        page_offset: int,
    ) -> List[UUID]:
        touched_product_ids: List[UUID] = []
        touched_product_id_set: set[UUID] = set()
        pending_eav_rows: List[tuple[UUID, str, Any]] = []
        pending_category_updates: List[tuple[UUID, Any]] = []
        category_cache: Dict[str, int] = {}
        bulk_eav_enabled = bool(getattr(settings, "KLEVU_SYNC_BULK_EAV_ENABLED", True))
        row_savepoint_enabled = bool(getattr(settings, "KLEVU_SYNC_ROW_SAVEPOINT_ENABLED", True))
        payload_rows: List[tuple[Mapping[str, Any], Dict[str, Any]]] = []
        for record in records:
            payload = self._record_to_payload(record)
            if payload is None:
                stats.skipped += 1
                continue
            payload_rows.append((record, payload))

        if not payload_rows:
            return touched_product_ids

        lookup_context = await self._build_page_lookup_context(
            db,
            payloads=[payload for _, payload in payload_rows],
        )
        await self._preload_groups(
            db,
            master_codes=[payload.get("master_code") for _, payload in payload_rows],
            cache=group_cache,
        )

        for record, payload in payload_rows:
            try:
                if row_savepoint_enabled:
                    async with db.begin_nested():
                        action, product_id = await self._upsert_payload(
                            db,
                            payload=payload,
                            group_cache=group_cache,
                            stats=stats,
                            lookup_context=lookup_context,
                            pending_eav_rows=pending_eav_rows,
                            pending_category_updates=pending_category_updates,
                        )
                else:
                    action, product_id = await self._upsert_payload(
                        db,
                        payload=payload,
                        group_cache=group_cache,
                        stats=stats,
                        lookup_context=lookup_context,
                        pending_eav_rows=pending_eav_rows,
                        pending_category_updates=pending_category_updates,
                    )
                if action != "unchanged" and product_id not in touched_product_id_set:
                    touched_product_id_set.add(product_id)
                    touched_product_ids.append(product_id)
                if action == "created":
                    stats.created += 1
                elif action == "updated":
                    stats.updated += 1
                elif action == "unchanged":
                    stats.skipped += 1
                else:
                    logger.warning(
                        "Unexpected upsert action '%s' at offset=%s sku=%s",
                        action,
                        page_offset,
                        payload.get("sku"),
                    )
                    stats.updated += 1
            except Exception as exc:  # intentionally broad to isolate row failures
                stats.failed += 1
                logger.warning(
                    "Klevu row upsert failed at offset=%s sku=%s error=%s",
                    page_offset,
                    payload.get("sku"),
                    exc,
                )
                if run_id is not None:
                    await self._record_failure(
                        db,
                        run_id=run_id,
                        page_offset=page_offset,
                        payload=payload,
                        record=record,
                        error=exc,
                    )
                if not row_savepoint_enabled:
                    raise
        if bulk_eav_enabled and pending_eav_rows:
            try:
                await eav_service.bulk_upsert_product_attribute_rows(
                    db,
                    rows=pending_eav_rows,
                    drop_empty=False,
                )
            except Exception:
                logger.exception(
                    "Bulk EAV upsert failed during Klevu sync page offset=%s; falling back to per-row writes",
                    page_offset,
                )
                for product_id, key, value in pending_eav_rows:
                    await eav_service.upsert_product_attributes(
                        db,
                        product_id=product_id,
                        attributes={key: value},
                        drop_empty=False,
                    )
        if bool(getattr(settings, "FACETS_V2_DUAL_WRITE_ENABLED", True)) and pending_category_updates:
            for product_id, raw_category in pending_category_updates:
                try:
                    await category_taxonomy_service.sync_product_categories(
                        db,
                        product_id=product_id,
                        raw_category=raw_category,
                        source="klevu",
                        category_cache=category_cache,
                        clear_when_empty=True,
                    )
                except Exception:
                    logger.exception(
                        "Category taxonomy dual-write failed during Klevu sync page offset=%s product_id=%s",
                        page_offset,
                        product_id,
                    )
                    if not row_savepoint_enabled:
                        raise
        if touched_product_ids and getattr(settings, "CHAT_PROJECTION_DUAL_WRITE_ENABLED", False):
            try:
                await product_projection_sync_service.sync_products_by_ids(
                    db,
                    product_ids=touched_product_ids,
                )
            except Exception:
                logger.exception("Projection dual-write failed during Klevu sync")
        return touched_product_ids
