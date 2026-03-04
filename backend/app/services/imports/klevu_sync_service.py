from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.klevu_sync import KlevuSyncFailure, KlevuSyncRun, KlevuSyncRunStatus
from app.models.product import Product, ProductEmbedding
from app.models.product_attribute import ProductAttributeValue
from app.models.product_change import ProductChange
from app.models.product_group import ProductGroup
from app.models.product_search_projection import ProductSearchProjection
from app.services.catalog.attributes_service import eav_service
from app.services.catalog.attribute_sync_service import ATTRIBUTE_FIELDS, product_attribute_sync_service
from app.services.catalog.category_taxonomy_service import category_taxonomy_service
from app.services.catalog.projection_service import product_projection_sync_service
from app.services.imports.products.parser import parse_bool, parse_int, parse_stock_status
from app.utils.pagination import normalize_pagination

logger = get_logger(__name__)


@dataclass
class KlevuSyncStats:
    fetched_records: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    request_count: int = 0
    backoff_count: int = 0
    last_offset: int = 0
    deduped_legacy_rows: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "fetched_records": int(self.fetched_records),
            "created": int(self.created),
            "updated": int(self.updated),
            "skipped": int(self.skipped),
            "failed": int(self.failed),
            "request_count": int(self.request_count),
            "backoff_count": int(self.backoff_count),
            "last_offset": int(self.last_offset),
            "deduped_legacy_rows": int(self.deduped_legacy_rows),
        }

    @classmethod
    def from_run(cls, run: KlevuSyncRun) -> "KlevuSyncStats":
        return cls(
            fetched_records=int(run.fetched_records or 0),
            created=int(run.created or 0),
            updated=int(run.updated or 0),
            skipped=int(run.skipped or 0),
            failed=int(run.failed or 0),
            request_count=int(run.request_count or 0),
            backoff_count=int(run.backoff_count or 0),
            last_offset=int(run.last_success_offset or 0),
            deduped_legacy_rows=0,
        )


@dataclass
class ProductResolution:
    selected: Optional[Product]
    duplicates: List[Product]


@dataclass
class PageLookupContext:
    products_by_sku: Dict[str, List[Product]]
    products_by_object_id: Dict[str, List[Product]]


class KlevuProductSyncService:
    _ACTIVE_RUN_STATUSES = {KlevuSyncRunStatus.pending, KlevuSyncRunStatus.running}

    def __init__(self) -> None:
        self._last_request_ts = 0.0
        self._background_tasks: Dict[UUID, asyncio.Task[None]] = {}

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _resolved_rpm(requests_per_minute: int | None) -> int:
        return int(requests_per_minute or getattr(settings, "KLEVU_SYNC_REQUESTS_PER_MINUTE", 180))

    def _build_run_config_snapshot(
        self,
        *,
        page_size: int,
        max_pages: int | None,
        requests_per_minute: int | None,
        stop_after_pages: int | None,
    ) -> Dict[str, Any]:
        return {
            "page_size": int(page_size),
            "max_pages": None if max_pages is None else int(max_pages),
            "requests_per_minute": self._resolved_rpm(requests_per_minute),
            "stop_after_pages": None if stop_after_pages is None else int(stop_after_pages),
            "payload_max_bytes": int(getattr(settings, "KLEVU_SYNC_PAYLOAD_MAX_BYTES", 2 * 1024 * 1024)),
            "disable_grouping": bool(getattr(settings, "KLEVU_SYNC_DISABLE_GROUPING", True)),
            "bulk_eav_enabled": bool(getattr(settings, "KLEVU_SYNC_BULK_EAV_ENABLED", True)),
        }

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).replace("\x00", " ").strip()
        return re.sub(r"\s+", " ", text)

    @classmethod
    def _as_str(cls, value: Any) -> str:
        return cls._clean_text(value)

    @staticmethod
    def _first_non_empty(*values: Any) -> str:
        for value in values:
            text = KlevuProductSyncService._clean_text(value)
            if text:
                return text
        return ""

    @classmethod
    def _normalize_image_url(cls, value: Any) -> str:
        url = cls._clean_text(value)
        if not url:
            return ""
        return re.sub(r"/wholesale1_t/", "/wholesale1_b/", url, flags=re.IGNORECASE)

    @staticmethod
    def _parse_optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = KlevuProductSyncService._clean_text(value)
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @classmethod
    def _normalize_currency(cls, value: Any) -> Optional[str]:
        text = cls._clean_text(value).upper()
        return text or None

    @classmethod
    def _split_compound_sku(cls, raw_sku: str) -> tuple[str, str]:
        text = cls._clean_text(raw_sku)
        if not text:
            return "", ""
        if ";;;;" not in text:
            return "", text
        parts = [cls._clean_text(part) for part in text.split(";;;;") if cls._clean_text(part)]
        if not parts:
            return "", ""
        parent_clean = parts[0]
        for token in parts:
            if token.upper().endswith("-000000"):
                return parent_clean, token
        return parent_clean, parts[-1]

    @classmethod
    def _derive_master_code(
        cls,
        *,
        record: Mapping[str, Any],
        parent_sku: str,
        canonical_sku: str,
    ) -> str:
        explicit = cls._first_non_empty(record.get("master_code"), record.get("masterCode"))
        if explicit:
            return explicit
        if parent_sku:
            return parent_sku
        if canonical_sku.upper().endswith("-000000"):
            base = cls._clean_text(canonical_sku[:-7]).strip("-_ ")
            if base:
                return base
        grouped = cls._first_non_empty(
            record.get("parentSku"),
            record.get("groupId"),
            record.get("itemGroupId"),
        )
        if grouped:
            return grouped
        if "-" in canonical_sku:
            prefix = canonical_sku.split("-", 1)[0].strip()
            if prefix:
                return prefix
        return canonical_sku

    @staticmethod
    def _parse_iso_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return str(value)

    @staticmethod
    def _normalize_klevu_category(value: Any) -> Optional[str]:
        return category_taxonomy_service.normalize_category_string(value)

    @staticmethod
    def _normalize_category_value(value: Any) -> Optional[str]:
        return category_taxonomy_service.normalize_category_string(value)

    @staticmethod
    def _extract_attributes(record: Mapping[str, Any]) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {}
        source_map = {
            "material": "material",
            "material_name": "material",
            "materialName": "material",
            "jewelry_type": "jewelry_type",
            "jewelryType": "jewelry_type",
            "jewellery_type": "jewelry_type",
            "color": "color",
            "colour": "color",
            "gauge": "gauge",
            "threading": "threading",
            "length": "length",
            "size": "size",
            "opal_color": "opal_color",
            "outer_diameter": "outer_diameter",
            "cz_color": "cz_color",
            "crystal_color": "crystal_color",
            "pearl_color": "pearl_color",
            "design": "design",
            "rack": "rack",
            "height": "height",
            "packing_option": "packing_option",
            "pincher_size": "pincher_size",
            "ring_size": "ring_size",
            "size_in_pack": "size_in_pack",
            "quantity_in_bulk": "quantity_in_bulk",
            "category": "category",
        }
        for source_key, target_key in source_map.items():
            value = record.get(source_key)
            if value is None:
                continue
            if target_key == "category":
                text = KlevuProductSyncService._normalize_category_value(value) or ""
            else:
                text = KlevuProductSyncService._clean_text(value)
            if text:
                attrs[target_key] = text
        if "category" not in attrs:
            normalized_category = KlevuProductSyncService._normalize_klevu_category(record.get("klevu_category"))
            if normalized_category:
                attrs["category"] = normalized_category
        return attrs

    @classmethod
    def _collect_legacy_skus(
        cls,
        *,
        record: Mapping[str, Any],
        raw_sku: str,
        parent_sku: str,
        canonical_sku: str,
    ) -> List[str]:
        values: List[str] = []
        if raw_sku and raw_sku != canonical_sku:
            values.append(raw_sku)
        if parent_sku and parent_sku not in {raw_sku, canonical_sku}:
            values.append(parent_sku)
        legacy_raw = cls._clean_text(record.get("legacy_sku"))
        if legacy_raw:
            for token in re.split(r"[|,]", legacy_raw):
                normalized = cls._clean_text(token)
                if normalized:
                    values.append(normalized)
        seen: set[str] = set()
        deduped: List[str] = []
        for item in values:
            lowered = item.lower()
            if lowered in seen or item == canonical_sku:
                continue
            seen.add(lowered)
            deduped.append(item)
        return deduped

    def _build_payload(self, *, api_key: str, limit: int, offset: int) -> Dict[str, Any]:
        search_settings: Dict[str, Any] = {
            "query": {"term": "*"},
            "typeOfRecords": ["KLEVU_PRODUCT"],
            "sortOrder": "updatedAt:desc",
            "limit": int(limit),
            "offset": int(offset),
        }
        if bool(getattr(settings, "KLEVU_SYNC_DISABLE_GROUPING", True)):
            search_settings["searchPrefs"] = ["disableGrouping"]
        return {
            "context": {"apiKeys": [api_key]},
            "recordQueries": [
                {
                    "id": "klevu_products_sync",
                    "typeOfRequest": "SEARCH",
                    "settings": search_settings,
                }
            ],
        }

    def _ensure_payload_size(self, payload: Mapping[str, Any], max_bytes: int) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > int(max_bytes):
            raise HTTPException(
                status_code=400,
                detail=f"Klevu payload too large ({len(encoded)} bytes > {max_bytes} bytes).",
            )

    async def _throttle(self, requests_per_minute: int) -> None:
        rpm = max(1, int(requests_per_minute))
        min_interval = 60.0 / float(rpm)
        now = time.monotonic()
        wait_for = min_interval - (now - self._last_request_ts)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        self._last_request_ts = time.monotonic()

    @staticmethod
    def _extract_records(response_json: Mapping[str, Any]) -> List[Dict[str, Any]]:
        queries = response_json.get("recordQueries")
        if isinstance(queries, list):
            for query in queries:
                if isinstance(query, Mapping) and isinstance(query.get("records"), list):
                    return [dict(r) for r in query["records"] if isinstance(r, Mapping)]
        query_results = response_json.get("queryResults")
        if isinstance(query_results, list):
            for query in query_results:
                if isinstance(query, Mapping) and isinstance(query.get("records"), list):
                    return [dict(r) for r in query["records"] if isinstance(r, Mapping)]
        return []

    async def _request_page(
        self,
        *,
        client: httpx.AsyncClient,
        payload: Mapping[str, Any],
        endpoint: str,
        max_retries: int,
        backoff_base_seconds: float,
        stats: KlevuSyncStats,
    ) -> Dict[str, Any]:
        retries = max(0, int(max_retries))
        attempt = 0
        while True:
            try:
                response = await client.post(endpoint, headers={"Content-Type": "application/json"}, json=payload)
            except httpx.HTTPError as exc:
                if attempt >= retries:
                    raise HTTPException(status_code=502, detail=f"Klevu request failed: {exc}") from exc
                stats.backoff_count += 1
                await asyncio.sleep(float(backoff_base_seconds) * (2**attempt) + random.uniform(0, 0.2))
                attempt += 1
                continue
            if response.status_code == 429:
                if attempt >= retries:
                    raise HTTPException(status_code=429, detail="Klevu rate limit exceeded after retries.")
                retry_after = response.headers.get("Retry-After")
                if retry_after and str(retry_after).strip().isdigit():
                    sleep_seconds = max(float(retry_after), 0.5)
                else:
                    sleep_seconds = float(backoff_base_seconds) * (2**attempt) + random.uniform(0, 0.3)
                stats.backoff_count += 1
                await asyncio.sleep(sleep_seconds)
                attempt += 1
                continue
            if response.status_code == 500:
                raise HTTPException(
                    status_code=502,
                    detail="Klevu returned 500. Validate request JSON body structure and required fields.",
                )
            if response.is_error:
                raise HTTPException(
                    status_code=502,
                    detail=f"Klevu request failed with status {response.status_code}: {response.text[:300]}",
                )
            try:
                return response.json()
            except ValueError as exc:
                raise HTTPException(status_code=502, detail="Klevu response is not valid JSON.") from exc

    def _record_to_payload(self, record: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        raw_sku = self._first_non_empty(
            record.get("sku"),
            record.get("SKU"),
            record.get("itemCode"),
            record.get("item_code"),
        )
        if not raw_sku:
            return None

        parent_sku, canonical_sku = self._split_compound_sku(raw_sku)
        if not canonical_sku:
            return None

        title = self._first_non_empty(
            record.get("name"),
            record.get("title"),
            record.get("productName"),
            canonical_sku,
        )
        # Klevu source of truth for product description.
        description = self._clean_text(record.get("shortDesc"))
        master_code = self._derive_master_code(
            record=record,
            parent_sku=parent_sku,
            canonical_sku=canonical_sku,
        )
        object_id = self._first_non_empty(
            record.get("object_id"),
            record.get("objectId"),
            record.get("id"),
            record.get("itemId"),
        ) or None

        price = self._parse_optional_float(
            self._first_non_empty(record.get("price"), record.get("salePrice"), record.get("listPrice"))
        )
        currency = self._normalize_currency(
            self._first_non_empty(
                record.get("currency"),
                record.get("currencyCode"),
                record.get("baseCurrency"),
                getattr(settings, "BASE_CURRENCY", "USD"),
            )
        ) or "USD"
        stock_qty = parse_int(
            self._first_non_empty(
                record.get("stock_qty"),
                record.get("stockQty"),
                record.get("quantity"),
                record.get("qty"),
            )
        )
        stock_status = parse_stock_status(
            self._first_non_empty(
                record.get("stock_status"),
                record.get("stockStatus"),
                record.get("inStock"),
                record.get("in_stock"),
                record.get("availability"),
            )
        )
        if stock_status is None:
            if stock_qty is not None:
                stock_status = "in_stock" if stock_qty > 0 else "out_of_stock"
            else:
                stock_status = "in_stock"

        image_url = self._normalize_image_url(
            self._first_non_empty(
                record.get("base_image"),
                record.get("baseImage"),
                record.get("image"),
                record.get("image_url"),
                record.get("thumbnail"),
                record.get("thumbnailImage"),
            )
        )
        product_url = self._first_non_empty(
            record.get("url"),
            record.get("product_url"),
            record.get("link"),
        )
        visibility = parse_bool(self._first_non_empty(record.get("visibility"), record.get("visible")))
        is_featured = parse_bool(self._first_non_empty(record.get("is_featured"), record.get("featured")))
        priority = parse_int(self._first_non_empty(record.get("priority"), record.get("rank"), record.get("sort_order")))

        attributes = self._extract_attributes(record)
        if raw_sku != canonical_sku:
            attributes["source_raw_sku"] = raw_sku
        attributes = product_attribute_sync_service.normalize_attributes(attributes)
        legacy_sku = self._collect_legacy_skus(
            record=record,
            raw_sku=raw_sku,
            parent_sku=parent_sku,
            canonical_sku=canonical_sku,
        )

        updated_at = self._parse_iso_datetime(
            self._first_non_empty(record.get("updatedAt"), record.get("updated_at"), record.get("lastUpdatedAt"))
        )

        return {
            "raw_sku": raw_sku,
            "sku": canonical_sku,
            "master_code": master_code,
            "title": title,
            "description": description or None,
            "object_id": object_id,
            "price": price,
            "currency": currency,
            "stock_status": stock_status,
            "stock_qty": stock_qty,
            "image_url": image_url or None,
            "product_url": product_url or None,
            "attributes": attributes,
            "legacy_sku": legacy_sku,
            "visibility": visibility,
            "is_featured": is_featured,
            "priority": priority,
            "updated_at": updated_at,
        }

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

    def _remove_product_lookup(
        self,
        context: PageLookupContext,
        *,
        product_id: UUID,
        sku: Optional[str],
        object_id: Optional[str],
    ) -> None:
        self._remove_lookup_entry(context.products_by_sku, sku, product_id)
        self._remove_lookup_entry(context.products_by_object_id, object_id, product_id)

    async def _build_page_lookup_context(
        self,
        db: AsyncSession,
        *,
        payloads: Sequence[Mapping[str, Any]],
    ) -> PageLookupContext:
        sku_terms: set[str] = set()
        object_ids: set[str] = set()
        for payload in payloads:
            sku = self._clean_text(payload.get("sku"))
            raw_sku = self._clean_text(payload.get("raw_sku"))
            object_id = self._clean_text(payload.get("object_id"))
            if sku:
                sku_terms.add(sku)
            if raw_sku:
                sku_terms.add(raw_sku)
            if object_id:
                object_ids.add(object_id)

        if not sku_terms and not object_ids:
            return PageLookupContext(products_by_sku={}, products_by_object_id={})

        if sku_terms and object_ids:
            stmt = select(Product).where(or_(Product.sku.in_(list(sku_terms)), Product.object_id.in_(list(object_ids))))
        elif sku_terms:
            stmt = select(Product).where(Product.sku.in_(list(sku_terms)))
        else:
            stmt = select(Product).where(Product.object_id.in_(list(object_ids)))

        result = await db.execute(stmt)
        context = PageLookupContext(products_by_sku={}, products_by_object_id={})
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

        candidates: List[Product] = []
        for key in (canonical_sku, raw_sku):
            if key:
                candidates.extend(lookup_context.products_by_sku.get(key, []))
        if object_id:
            candidates.extend(lookup_context.products_by_object_id.get(object_id, []))

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
        selected = canonical_match or raw_match or object_match
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
        selected = canonical_match or raw_match or object_match or matches[0]

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
            if payload.get("raw_sku") and payload["raw_sku"] != selected.sku and payload["raw_sku"] not in merged_legacy:
                merged_legacy.append(payload["raw_sku"])
            selected.legacy_sku = merged_legacy

            if not selected.object_id and duplicate.object_id:
                selected.object_id = duplicate.object_id
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
                )
            stats.deduped_legacy_rows += 1

    def _build_search_payload(
        self,
        *,
        product: Product,
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        return product_attribute_sync_service.build_search_document(
            display_name=payload["master_code"] or payload["sku"],
            sku=payload["sku"],
            object_id=payload.get("object_id"),
            description=payload.get("description"),
            legacy_skus=payload.get("legacy_sku") or [],
            attributes=payload.get("attributes") or {},
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
        category_cache: Optional[Dict[str, int]] = None,
    ) -> tuple[str, UUID]:
        if lookup_context is not None:
            resolution = self._resolve_existing_product_from_lookup(
                payload=payload,
                lookup_context=lookup_context,
            )
        else:
            resolution = await self._resolve_existing_product(db, payload)
        product = resolution.selected
        action = "updated" if product is not None else "created"
        previous_sku = product.sku if product is not None else None
        previous_object_id = product.object_id if product is not None else None

        group_id = await self._ensure_group(db, master_code=payload["master_code"], cache=group_cache)
        if product is None:
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
                object_id=payload.get("object_id"),
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
            previous_object_id = None

        if previous_sku and previous_sku != payload["sku"]:
            legacy = list(product.legacy_sku or [])
            if previous_sku not in legacy:
                legacy.append(previous_sku)
            product.legacy_sku = legacy

        product.sku = payload["sku"]
        product.master_code = payload["master_code"]
        product.group_id = group_id
        if payload.get("price") is not None:
            product.price = float(payload.get("price") or 0.0)
        product.currency = (payload.get("currency") or product.currency or "USD").upper()
        if payload.get("description"):
            product.description = payload["description"]
        product.stock_status = payload.get("stock_status") or product.stock_status
        product.stock_qty = payload.get("stock_qty")
        if payload.get("image_url"):
            product.image_url = payload["image_url"]
        if payload.get("product_url"):
            product.product_url = payload["product_url"]
        if payload.get("object_id"):
            product.object_id = payload["object_id"]
        if payload.get("visibility") is not None:
            product.visibility = bool(payload["visibility"])
        if payload.get("is_featured") is not None:
            product.is_featured = bool(payload["is_featured"])
        if payload.get("priority") is not None:
            product.priority = int(payload["priority"])
        product.last_stock_sync_at = self._now_utc()

        legacy_tokens = list(product.legacy_sku or [])
        for token in list(payload.get("legacy_sku") or []):
            if token and token not in legacy_tokens and token != product.sku:
                legacy_tokens.append(token)
        product.legacy_sku = legacy_tokens

        bulk_eav_enabled = bool(getattr(settings, "KLEVU_SYNC_BULK_EAV_ENABLED", True))
        if bulk_eav_enabled and pending_eav_rows is not None:
            merged_attributes = product_attribute_sync_service.merge_attributes(
                current=product.attributes or {},
                updates=payload.get("attributes") or {},
                drop_empty=False,
            )
            product.attributes = merged_attributes
        else:
            await product_attribute_sync_service.apply_dual_canonical(
                db=db,
                product=product,
                attribute_updates=payload.get("attributes") or {},
                drop_empty=False,
            )
        await category_taxonomy_service.sync_product_categories(
            db,
            product_id=product.id,
            raw_category=(product.attributes or {}).get("category"),
            source="klevu",
            category_cache=category_cache,
            clear_when_empty=True,
        )
        search_payload = self._build_search_payload(product=product, payload=payload)
        product.search_text = search_payload["search_text"]
        product.search_hash = search_payload["search_hash"]
        product.search_keywords = search_payload["search_keywords"]

        await self._merge_and_cleanup_duplicates(
            db,
            selected=product,
            duplicates=resolution.duplicates,
            payload=payload,
            stats=stats,
            lookup_context=lookup_context,
        )
        await db.flush()
        if lookup_context is not None:
            self._remove_product_lookup(
                lookup_context,
                product_id=product.id,
                sku=previous_sku,
                object_id=previous_object_id,
            )
            self._register_product_lookup(lookup_context, product)
        if bulk_eav_enabled and pending_eav_rows is not None:
            for key, value in (product.attributes or {}).items():
                pending_eav_rows.append((product.id, str(key), value))
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
        pending_eav_rows: List[tuple[UUID, str, Any]] = []
        category_cache: Dict[str, int] = {}
        bulk_eav_enabled = bool(getattr(settings, "KLEVU_SYNC_BULK_EAV_ENABLED", True))
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
                async with db.begin_nested():
                    action, product_id = await self._upsert_payload(
                        db,
                        payload=payload,
                        group_cache=group_cache,
                        stats=stats,
                        lookup_context=lookup_context,
                        pending_eav_rows=pending_eav_rows,
                        category_cache=category_cache,
                    )
                touched_product_ids.append(product_id)
                if action == "created":
                    stats.created += 1
                else:
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
                # Fallback path preserves correctness if the bulk SQL path fails for any environment-specific reason.
                for product_id, key, value in pending_eav_rows:
                    await eav_service.upsert_product_attributes(
                        db,
                        product_id=product_id,
                        attributes={key: value},
                        drop_empty=False,
                    )
        if touched_product_ids and getattr(settings, "CHAT_PROJECTION_DUAL_WRITE_ENABLED", False):
            try:
                await product_projection_sync_service.sync_products_by_ids(
                    db,
                    product_ids=touched_product_ids,
                )
            except Exception:
                logger.exception("Projection dual-write failed during Klevu sync")
        return touched_product_ids

    def _apply_run_stats(
        self,
        run: KlevuSyncRun,
        *,
        stats: KlevuSyncStats,
        current_offset: int,
    ) -> None:
        run.current_offset = int(current_offset)
        run.last_success_offset = int(stats.last_offset)
        run.fetched_records = int(stats.fetched_records)
        run.created = int(stats.created)
        run.updated = int(stats.updated)
        run.skipped = int(stats.skipped)
        run.failed = int(stats.failed)
        run.backoff_count = int(stats.backoff_count)
        run.request_count = int(stats.request_count)
        run.updated_at = self._now_utc()

    async def _sync_loop(
        self,
        db: AsyncSession,
        *,
        page_size: int,
        max_pages: int | None,
        requests_per_minute: int,
        start_offset: int,
        stop_after_pages: int | None,
        run: KlevuSyncRun | None,
    ) -> Dict[str, Any]:
        api_key = self._clean_text(getattr(settings, "KLEVU_JS_API_KEY", ""))
        if not api_key:
            raise HTTPException(status_code=400, detail="KLEVU_JS_API_KEY is not configured.")

        endpoint = (
            self._clean_text(getattr(settings, "KLEVU_API_ENDPOINT", ""))
            or "https://eucs30v2.ksearchnet.com/cs/v2/search"
        )
        max_payload_bytes = int(getattr(settings, "KLEVU_SYNC_PAYLOAD_MAX_BYTES", 2 * 1024 * 1024))
        timeout_seconds = float(getattr(settings, "KLEVU_SYNC_TIMEOUT_SECONDS", 30.0))
        max_retries = int(getattr(settings, "KLEVU_SYNC_MAX_RETRIES", 5))
        backoff_base_seconds = float(getattr(settings, "KLEVU_SYNC_BACKOFF_BASE_SECONDS", 0.5))
        page_cap = int(getattr(settings, "KLEVU_SYNC_PAGE_SIZE_MAX", 100))
        effective_page_size = min(max(int(page_size), 1), page_cap, 100)

        stats = KlevuSyncStats.from_run(run) if run is not None else KlevuSyncStats()
        offset = max(int(start_offset), 0)
        pages_processed = 0
        group_cache: Dict[str, UUID] = {}

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            while True:
                if max_pages is not None and pages_processed >= int(max_pages):
                    break
                if stop_after_pages is not None and pages_processed >= int(stop_after_pages):
                    if run is not None:
                        run.status = KlevuSyncRunStatus.stopped
                    break

                if run is not None:
                    await db.refresh(run)
                    if run.cancel_requested:
                        run.status = KlevuSyncRunStatus.cancelled
                        break

                payload = self._build_payload(api_key=api_key, limit=effective_page_size, offset=offset)
                self._ensure_payload_size(payload, max_bytes=max_payload_bytes)
                await self._throttle(requests_per_minute)
                response_json = await self._request_page(
                    client=client,
                    payload=payload,
                    endpoint=endpoint,
                    max_retries=max_retries,
                    backoff_base_seconds=backoff_base_seconds,
                    stats=stats,
                )
                stats.request_count += 1
                records = self._extract_records(response_json)
                if not records:
                    break

                await self._process_page_rows(
                    db,
                    records=records,
                    stats=stats,
                    group_cache=group_cache,
                    run_id=run.id if run is not None else None,
                    page_offset=offset,
                )
                stats.fetched_records += len(records)
                stats.last_offset = offset
                offset += effective_page_size
                pages_processed += 1

                if run is not None:
                    self._apply_run_stats(run, stats=stats, current_offset=offset)
                await db.commit()

                if len(records) < effective_page_size:
                    break

        return {
            "page_size": effective_page_size,
            "pages_processed": pages_processed,
            "next_offset": offset,
            "stats": stats,
        }

    @staticmethod
    def _serialize_run(run: KlevuSyncRun, *, include_config: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": str(run.id),
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            "page_size": run.page_size,
            "max_pages": run.max_pages,
            "current_offset": run.current_offset,
            "last_success_offset": run.last_success_offset,
            "fetched_records": run.fetched_records,
            "created": run.created,
            "updated": run.updated,
            "skipped": run.skipped,
            "failed": run.failed,
            "backoff_count": run.backoff_count,
            "request_count": run.request_count,
            "cancel_requested": bool(run.cancel_requested),
            "error_summary": run.error_summary,
        }
        if include_config:
            payload["config_snapshot"] = run.config_snapshot or {}
        return payload

    async def _ensure_no_active_run(self, db: AsyncSession, *, ignore_run_id: UUID | None = None) -> None:
        stmt = select(KlevuSyncRun).where(KlevuSyncRun.status.in_(list(self._ACTIVE_RUN_STATUSES)))
        if ignore_run_id is not None:
            stmt = stmt.where(KlevuSyncRun.id != ignore_run_id)
        existing = (await db.execute(stmt.order_by(desc(KlevuSyncRun.started_at)))).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A Klevu full sync is already active (run_id={existing.id}).",
            )

    async def _run_full_sync_background(
        self,
        *,
        run_id: UUID,
        requests_per_minute: int | None,
        max_pages: int | None,
        stop_after_pages: int | None,
    ) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await self._execute_full_sync_run(
                    db,
                    run_id=run_id,
                    requests_per_minute=requests_per_minute,
                    max_pages=max_pages,
                    stop_after_pages=stop_after_pages,
                )
        except Exception:
            logger.exception("Klevu background full sync task failed: run_id=%s", run_id)
        finally:
            self._background_tasks.pop(run_id, None)

    async def _execute_full_sync_run(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        requests_per_minute: int | None,
        max_pages: int | None,
        stop_after_pages: int | None,
    ) -> Dict[str, Any]:
        run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Klevu sync run not found.")

        run.status = KlevuSyncRunStatus.running
        run.cancel_requested = False
        run.error_summary = None
        run.completed_at = None
        run.updated_at = self._now_utc()
        await db.commit()

        rpm = self._resolved_rpm(requests_per_minute)
        run_max_pages = max_pages if max_pages is not None else run.max_pages
        run.config_snapshot = self._build_run_config_snapshot(
            page_size=run.page_size,
            max_pages=run_max_pages,
            requests_per_minute=rpm,
            stop_after_pages=stop_after_pages,
        )
        try:
            result = await self._sync_loop(
                db,
                page_size=run.page_size,
                max_pages=run_max_pages,
                requests_per_minute=rpm,
                start_offset=run.current_offset or 0,
                stop_after_pages=stop_after_pages,
                run=run,
            )
            await db.refresh(run)
            if run.status == KlevuSyncRunStatus.running:
                run.status = KlevuSyncRunStatus.completed
            if run.status in {KlevuSyncRunStatus.completed, KlevuSyncRunStatus.cancelled, KlevuSyncRunStatus.stopped}:
                run.completed_at = self._now_utc()
            run.updated_at = self._now_utc()
            await db.commit()
            await db.refresh(run)
            return {
                "run": self._serialize_run(run, include_config=True),
                "runtime": {
                    "pages_processed": result["pages_processed"],
                    "next_offset": result["next_offset"],
                },
            }
        except HTTPException as exc:
            await db.rollback()
            run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
            if run is not None:
                run.status = KlevuSyncRunStatus.failed
                run.error_summary = str(exc.detail)[:2000]
                run.completed_at = self._now_utc()
                run.updated_at = self._now_utc()
                await db.commit()
            raise
        except Exception as exc:
            await db.rollback()
            logger.exception("Klevu full sync run failed: run_id=%s", run_id)
            run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
            if run is not None:
                run.status = KlevuSyncRunStatus.failed
                run.error_summary = str(exc)[:2000]
                run.completed_at = self._now_utc()
                run.updated_at = self._now_utc()
                await db.commit()
            raise HTTPException(status_code=500, detail=f"Klevu full sync failed: {exc}") from exc

    async def sync_recent_products(
        self,
        db: AsyncSession,
        *,
        max_pages: int = 10,
        page_size: int = 100,
        requests_per_minute: int | None = None,
    ) -> Dict[str, Any]:
        rpm = self._resolved_rpm(requests_per_minute)
        result = await self._sync_loop(
            db,
            page_size=page_size,
            max_pages=max_pages,
            requests_per_minute=rpm,
            start_offset=0,
            stop_after_pages=None,
            run=None,
        )
        return {
            "mode": "manual",
            "status": "completed",
            "page_size": result["page_size"],
            "pages_processed": result["pages_processed"],
            "next_offset": result["next_offset"],
            "stats": result["stats"].as_dict(),
            "requests_per_minute": rpm,
        }

    async def start_full_sync(
        self,
        db: AsyncSession,
        *,
        page_size: int = 100,
        max_pages: int | None = None,
        requests_per_minute: int | None = None,
        stop_after_pages: int | None = None,
    ) -> Dict[str, Any]:
        await self._ensure_no_active_run(db)
        page_cap = int(getattr(settings, "KLEVU_SYNC_PAGE_SIZE_MAX", 100))
        effective_page_size = min(max(int(page_size), 1), page_cap, 100)
        run = KlevuSyncRun(
            status=KlevuSyncRunStatus.pending,
            page_size=effective_page_size,
            max_pages=max_pages,
            current_offset=0,
            last_success_offset=0,
            config_snapshot=self._build_run_config_snapshot(
                page_size=effective_page_size,
                max_pages=max_pages,
                requests_per_minute=requests_per_minute,
                stop_after_pages=stop_after_pages,
            ),
            cancel_requested=False,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        task = asyncio.create_task(
            self._run_full_sync_background(
                run_id=run.id,
                requests_per_minute=requests_per_minute,
                max_pages=max_pages,
                stop_after_pages=stop_after_pages,
            )
        )
        self._background_tasks[run.id] = task
        return {"run": self._serialize_run(run, include_config=True)}

    async def resume_full_sync(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        max_pages: int | None = None,
        requests_per_minute: int | None = None,
        stop_after_pages: int | None = None,
    ) -> Dict[str, Any]:
        run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Klevu sync run not found.")
        if run.status not in {KlevuSyncRunStatus.failed, KlevuSyncRunStatus.cancelled, KlevuSyncRunStatus.stopped}:
            raise HTTPException(status_code=400, detail=f"Run {run_id} is not resumable (status={run.status.value}).")

        await self._ensure_no_active_run(db, ignore_run_id=run_id)
        run.status = KlevuSyncRunStatus.pending
        run.error_summary = None
        run.cancel_requested = False
        run.completed_at = None
        if max_pages is not None:
            run.max_pages = max_pages
        run.config_snapshot = self._build_run_config_snapshot(
            page_size=run.page_size,
            max_pages=run.max_pages,
            requests_per_minute=requests_per_minute,
            stop_after_pages=stop_after_pages,
        )
        run.updated_at = self._now_utc()
        await db.commit()
        await db.refresh(run)

        task = asyncio.create_task(
            self._run_full_sync_background(
                run_id=run.id,
                requests_per_minute=requests_per_minute,
                max_pages=max_pages if max_pages is not None else run.max_pages,
                stop_after_pages=stop_after_pages,
            )
        )
        self._background_tasks[run.id] = task
        return {"run": self._serialize_run(run, include_config=True)}

    async def run_full_sync_cli(
        self,
        db: AsyncSession,
        *,
        page_size: int = 100,
        max_pages: int | None = None,
        requests_per_minute: int | None = None,
        stop_after_pages: int | None = None,
        resume_run_id: UUID | None = None,
    ) -> Dict[str, Any]:
        if resume_run_id is not None:
            run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == resume_run_id))).scalar_one_or_none()
            if run is None:
                raise HTTPException(status_code=404, detail="Klevu sync run not found.")
            if run.status not in {KlevuSyncRunStatus.failed, KlevuSyncRunStatus.cancelled, KlevuSyncRunStatus.stopped}:
                raise HTTPException(status_code=400, detail=f"Run {resume_run_id} is not resumable.")
            await self._ensure_no_active_run(db, ignore_run_id=run.id)
            run.status = KlevuSyncRunStatus.pending
            run.error_summary = None
            run.cancel_requested = False
            run.completed_at = None
            run.updated_at = self._now_utc()
            if max_pages is not None:
                run.max_pages = max_pages
            run.config_snapshot = self._build_run_config_snapshot(
                page_size=run.page_size,
                max_pages=run.max_pages,
                requests_per_minute=requests_per_minute,
                stop_after_pages=stop_after_pages,
            )
            await db.commit()
            await db.refresh(run)
            return await self._execute_full_sync_run(
                db,
                run_id=run.id,
                requests_per_minute=requests_per_minute,
                max_pages=max_pages if max_pages is not None else run.max_pages,
                stop_after_pages=stop_after_pages,
            )

        await self._ensure_no_active_run(db)
        page_cap = int(getattr(settings, "KLEVU_SYNC_PAGE_SIZE_MAX", 100))
        effective_page_size = min(max(int(page_size), 1), page_cap, 100)
        run = KlevuSyncRun(
            status=KlevuSyncRunStatus.pending,
            page_size=effective_page_size,
            max_pages=max_pages,
            current_offset=0,
            last_success_offset=0,
            cancel_requested=False,
            config_snapshot=self._build_run_config_snapshot(
                page_size=effective_page_size,
                max_pages=max_pages,
                requests_per_minute=requests_per_minute,
                stop_after_pages=stop_after_pages,
            ),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return await self._execute_full_sync_run(
            db,
            run_id=run.id,
            requests_per_minute=requests_per_minute,
            max_pages=max_pages,
            stop_after_pages=stop_after_pages,
        )

    async def get_full_sync_run(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        include_failures: bool = False,
        failure_limit: int = 50,
    ) -> Dict[str, Any]:
        run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Klevu sync run not found.")
        payload = self._serialize_run(run, include_config=True)
        if include_failures:
            stmt = (
                select(KlevuSyncFailure)
                .where(KlevuSyncFailure.run_id == run_id)
                .order_by(desc(KlevuSyncFailure.created_at))
                .limit(max(1, int(failure_limit)))
            )
            result = await db.execute(stmt)
            payload["failures"] = [
                {
                    "id": str(item.id),
                    "page_offset": item.page_offset,
                    "raw_sku": item.raw_sku,
                    "canonical_sku": item.canonical_sku,
                    "error_type": item.error_type,
                    "error_message": item.error_message,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in result.scalars().all()
            ]
        payload["failure_count"] = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(KlevuSyncFailure)
                    .where(KlevuSyncFailure.run_id == run_id)
                )
            ).scalar()
            or 0
        )
        return payload

    async def list_full_sync_runs(self, db: AsyncSession, *, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        total = int((await db.execute(select(func.count()).select_from(KlevuSyncRun))).scalar() or 0)
        safe_page, total_pages, offset = normalize_pagination(total_items=total, page=page, page_size=page_size)
        stmt = (
            select(KlevuSyncRun)
            .order_by(desc(KlevuSyncRun.started_at))
            .offset(offset)
            .limit(page_size)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return {
            "items": [self._serialize_run(item, include_config=False) for item in rows],
            "totalItems": total,
            "page": safe_page,
            "pageSize": page_size,
            "totalPages": total_pages,
        }

    async def request_full_sync_cancel(self, db: AsyncSession, *, run_id: UUID) -> Dict[str, Any]:
        run = (await db.execute(select(KlevuSyncRun).where(KlevuSyncRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Klevu sync run not found.")
        if run.status in {KlevuSyncRunStatus.completed, KlevuSyncRunStatus.failed, KlevuSyncRunStatus.cancelled}:
            return {"run": self._serialize_run(run, include_config=True), "updated": False}
        run.cancel_requested = True
        run.updated_at = self._now_utc()
        await db.commit()
        await db.refresh(run)
        return {"run": self._serialize_run(run, include_config=True), "updated": True}


klevu_product_sync_service = KlevuProductSyncService()
