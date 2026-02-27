import asyncio
import csv
import io
import json
import re
import enum
import random
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from uuid import uuid4, UUID
from datetime import datetime
from fastapi import UploadFile, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update, delete, or_, exists
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from app.models.product import Product, ProductEmbedding
from app.models.product_group import ProductGroup
from app.models.product_change import ProductChange
from app.models.knowledge import (
    KnowledgeArticle,
    KnowledgeArticleVersion,
    KnowledgeChunk,
    KnowledgeEmbedding,
    KnowledgeUpload,
    KnowledgeUploadStatus,
)
from app.models.product_upload import ProductUpload, ProductUploadStatus
from app.services.ai.llm_service import llm_service
from app.services.tasks.service import task_service
from app.services.catalog.attributes_service import eav_service
from app.services.catalog.attribute_sync_service import product_attribute_sync_service
from app.services.catalog.projection_service import product_projection_sync_service
from app.services.imports.knowledge.chunking import chunk_text
from app.services.imports.knowledge.embeddings import hash_text
from app.services.imports.knowledge.parser import parse_csv_knowledge
from app.services.imports.knowledge.upload_history import (
    ensure_upload_path_in_root as ensure_knowledge_upload_path_in_root,
    knowledge_upload_storage_path,
)
from app.services.imports.products.embeddings import (
    is_embedding_payload_too_large,
    is_transient_embedding_error,
)
from app.services.imports.products.parser import parse_bool, parse_float, parse_int, parse_stock_status
from app.services.imports.products.search_text_builder import (
    DEFAULT_ATTRIBUTE_COLUMNS,
    DEFAULT_SEARCH_KEYWORD_COLUMNS,
    build_search_keywords,
    build_search_synonyms,
    build_search_text,
    expand_search_terms,
    normalize_attribute_value,
    normalize_search_text,
)
from app.services.imports.products.upload_history import (
    ensure_upload_path_in_root as ensure_product_upload_path_in_root,
    product_upload_storage_path,
)
from app.models.task import TaskType, TaskStatus
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)

ATTRIBUTE_COLUMNS = list(DEFAULT_ATTRIBUTE_COLUMNS)
SEARCH_KEYWORD_COLUMNS = list(DEFAULT_SEARCH_KEYWORD_COLUMNS)

class DataImportService:
    @staticmethod
    def _parse_int(value: Any) -> int | None:
        return parse_int(value)

    @staticmethod
    def _parse_float(value: Any) -> float:
        return parse_float(value)

    @staticmethod
    def _parse_bool(value: Any) -> bool | None:
        return parse_bool(value)

    @staticmethod
    def _parse_stock_status(value: Any) -> str | None:
        return parse_stock_status(value)

    @staticmethod
    def _normalize_search_text(text: str) -> str:
        return normalize_search_text(text)

    def _normalize_keyword(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        return self._normalize_search_text(text)

    def _normalize_material(self, value: str) -> str:
        normalized = normalize_attribute_value("material", value)
        if isinstance(normalized, str):
            return normalized
        return value.strip()

    def _normalize_gauge(self, value: str) -> str:
        normalized = normalize_attribute_value("gauge", value)
        if isinstance(normalized, str):
            return normalized
        return value.strip()

    def _normalize_threading(self, value: str) -> str:
        normalized = normalize_attribute_value("threading", value)
        if isinstance(normalized, str):
            return normalized
        return value.strip()

    def _normalize_jewelry_type(self, value: str) -> str:
        normalized = normalize_attribute_value("jewelry_type", value)
        if isinstance(normalized, str):
            return normalized
        return value.strip()

    def _normalize_attribute_value(self, key: str, value: Any) -> Any:
        return normalize_attribute_value(key, value)

    def _build_search_synonyms(self, attributes: Dict[str, Any]) -> List[str]:
        return build_search_synonyms(attributes, keyword_columns=SEARCH_KEYWORD_COLUMNS)

    def _build_search_keywords(
        self,
        *,
        display_name: str,
        sku: str,
        legacy_skus: List[str],
        attributes: Dict[str, Any],
        keyword_columns: List[str],
    ) -> List[str]:
        return build_search_keywords(
            display_name=display_name,
            sku=sku,
            legacy_skus=legacy_skus,
            attributes=attributes,
            keyword_columns=keyword_columns,
        )

    @staticmethod
    def _expand_search_terms(values: List[Any]) -> List[str]:
        return expand_search_terms(values)

    def _build_search_text(
        self,
        *,
        display_name: str,
        sku: str,
        object_id: str | None,
        description: str | None,
        legacy_skus: List[str],
        synonyms: List[str],
        attributes: Dict[str, Any],
        attribute_columns: List[str],
    ) -> str:
        return build_search_text(
            display_name=display_name,
            sku=sku,
            object_id=object_id,
            description=description,
            legacy_skus=legacy_skus,
            synonyms=synonyms,
            attributes=attributes,
            attribute_columns=attribute_columns,
        )

    def _serialize_change_value(self, value: Any) -> Any:
        if isinstance(value, enum.Enum):
            return value.value
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, list):
            return [self._serialize_change_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self._serialize_change_value(v) for k, v in value.items()}
        return value

    def _collect_product_changes(
        self,
        *,
        product: Product,
        updates: Dict[str, Any],
    ) -> Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
        changed_fields: List[str] = []
        old_values: Dict[str, Any] = {}
        new_values: Dict[str, Any] = {}
        for field, new_value in updates.items():
            old_value = getattr(product, field)
            old_serialized = self._serialize_change_value(old_value)
            new_serialized = self._serialize_change_value(new_value)
            if old_serialized == new_serialized:
                continue
            changed_fields.append(field)
            old_values[field] = old_serialized
            new_values[field] = new_serialized
        return changed_fields, old_values, new_values

    @staticmethod
    def get_product_template() -> str:
        """Returns the CSV header for products."""
        # master_code allows grouping multiple SKUs. stock_status can be 'in_stock' or 'out_of_stock'.
        return (
            "sku,master_code,price,stock_status,stock_qty,description,category,image_url,product_url,object_id,"
            "legacy_sku,visibility,is_featured,priority,search_keywords,attributes_json,"
            "jewelry_type,material,"
            "length,size,cz_color,design,crystal_color,color,gauge,size_in_pack,rack,height,"
            "packing_option,pincher_size,ring_size,quantity_in_bulk,opal_color,threading,"
            "outer_diameter,pearl_color"
        )

    @staticmethod
    def get_knowledge_template() -> str:
        """Returns the CSV header for knowledge articles."""
        return "title,content,category,url"
        
    async def import_products(
        self,
        db: AsyncSession,
        file: UploadFile,
        background_tasks: BackgroundTasks = None,
        uploaded_by: str | None = None
    ) -> Dict[str, Any]:
        content = await file.read()
        upload_record = await self._create_product_upload(
            db=db,
            content=content,
            filename=file.filename,
            content_type=file.content_type,
            uploaded_by=uploaded_by,
        )

        # Decode bytes to string
        text_content = content.decode("utf-8-sig")  # Handle BOM
        csv_reader = csv.DictReader(io.StringIO(text_content))

        stats = {"created": 0, "updated": 0, "errors": 0}
        group_cache: Dict[str, UUID] = {}
        pending_eav_rows: List[Tuple[UUID, str, Any]] = []
        pending_new_eav: List[Tuple[Product, Dict[str, Any]]] = []
        pending_projection_products: List[Product] = []

        try:
            await self._update_product_upload_status(db, upload_record.id, ProductUploadStatus.PROCESSING)
            for row in csv_reader:
                try:
                    # Basic Validation
                    if not row.get("sku"):
                        continue

                    sku = row["sku"].strip()
                    row_desc = row.get("description", "")

                    master_code_raw = row.get("master_code")
                    master_code = (master_code_raw.strip() if isinstance(master_code_raw, str) else master_code_raw) or None
                    row_name = row.get("name")
                    row_name = (row_name.strip() if isinstance(row_name, str) else row_name) or None
                    display_name = master_code or row_name or sku
                    group_id: UUID | None = None
                    if display_name:
                        cached = group_cache.get(display_name)
                        if cached:
                            group_id = cached
                        else:
                            stmt = select(ProductGroup).where(ProductGroup.master_code == display_name)
                            result = await db.execute(stmt)
                            group = result.scalar_one_or_none()
                            if not group:
                                group = ProductGroup(master_code=display_name)
                                db.add(group)
                                await db.flush()
                            group_id = group.id
                            group_cache[display_name] = group_id

                    object_id_raw = row.get("object_id")
                    object_id = (object_id_raw.strip() if isinstance(object_id_raw, str) else object_id_raw) or None
                    legacy_raw = row.get("legacy_sku")
                    legacy_skus: List[str] = []
                    if isinstance(legacy_raw, str) and legacy_raw.strip():
                        legacy_skus = [s.strip() for s in re.split(r"[|,]", legacy_raw) if s.strip()]

                    stock_status = self._parse_stock_status(row.get("stock_status"))
                    stock_qty = self._parse_int(row.get("stock_qty"))
                    visibility = self._parse_bool(row.get("visibility"))
                    is_featured = self._parse_bool(row.get("is_featured"))
                    priority = self._parse_int(row.get("priority"))

                    image_url = row.get("image_url")
                    if isinstance(image_url, str):
                        image_url = image_url.strip() or None

                    product_url = row.get("product_url")
                    if isinstance(product_url, str):
                        product_url = product_url.strip() or None
                    
                    # Parse attributes:
                    # - attributes_json (optional): JSON object string
                    # - explicit columns (optional): preferred for spreadsheet usage
                    attributes: Dict[str, Any] = {}
                    attributes_json_raw = row.get("attributes_json")
                    if isinstance(attributes_json_raw, str) and attributes_json_raw.strip():
                        try:
                            parsed = json.loads(attributes_json_raw)
                            if isinstance(parsed, dict):
                                attributes.update(parsed)
                        except Exception:
                            # Non-fatal: treat as missing
                            pass

                    for key in ATTRIBUTE_COLUMNS:
                        val = row.get(key)
                        if val is None:
                            continue
                        if isinstance(val, str):
                            val = val.strip()
                            if not val:
                                continue
                        normalized = self._normalize_attribute_value(key, val)
                        if normalized is not None:
                            attributes[key] = normalized

                    for key in ATTRIBUTE_COLUMNS:
                        if key in attributes:
                            normalized = self._normalize_attribute_value(key, attributes[key])
                            if normalized is not None:
                                attributes[key] = normalized
                    attributes = product_attribute_sync_service.normalize_attributes(attributes)

                    category_raw = row.get("category")
                    category = category_raw.strip() if isinstance(category_raw, str) else category_raw
                    if isinstance(category, str) and category.strip():
                        attributes["category"] = category.strip()

                    # Check exist
                    stmt = select(Product).where(Product.sku == sku)
                    result = await db.execute(stmt)
                    existing_product = result.scalar_one_or_none()
                    if existing_product and existing_product.legacy_sku and not legacy_skus:
                        legacy_skus = list(existing_product.legacy_sku)

                    if stock_status is None:
                        if existing_product:
                            stock_status = existing_product.stock_status
                        else:
                            stock_status = "in_stock"
                    if stock_qty is None and existing_product:
                        stock_qty = existing_product.stock_qty

                    if visibility is None and existing_product:
                        visibility = existing_product.visibility
                    if is_featured is None and existing_product:
                        is_featured = existing_product.is_featured
                    if priority is None and existing_product:
                        priority = existing_product.priority

                    effective_attributes = attributes
                    if existing_product:
                        effective_attributes = attributes or (existing_product.attributes or {})

                    manual_keywords: List[str] = []
                    search_keywords_raw = row.get("search_keywords")
                    if isinstance(search_keywords_raw, str) and search_keywords_raw.strip():
                        for token in search_keywords_raw.split(","):
                            normalized = self._normalize_keyword(token)
                            if normalized:
                                manual_keywords.append(normalized)

                    search_payload = product_attribute_sync_service.build_search_document(
                        display_name=display_name,
                        sku=sku,
                        object_id=object_id,
                        description=row_desc,
                        legacy_skus=legacy_skus,
                        attributes=effective_attributes,
                        manual_keywords=manual_keywords,
                        attribute_columns=ATTRIBUTE_COLUMNS,
                    )
                    search_text = search_payload["search_text"]
                    search_keywords = search_payload["search_keywords"]
                    search_hash = search_payload["search_hash"]
                    stock_synced_at = datetime.utcnow()

                    if existing_product:
                        update_fields: Dict[str, Any] = {
                            "master_code": display_name,
                            "group_id": group_id,
                            "price": self._parse_float(row.get("price", 0)),
                            "currency": (getattr(settings, "BASE_CURRENCY", "USD") or "USD").upper(),
                            "description": row_desc,
                            "search_text": search_text,
                            "search_hash": search_hash,
                            "search_keywords": search_keywords,
                            "attributes": effective_attributes or (existing_product.attributes or {}),
                            "object_id": object_id,
                            "stock_status": stock_status,
                            "stock_qty": stock_qty,
                            "legacy_sku": legacy_skus,
                        }

                        if image_url is not None:
                            update_fields["image_url"] = image_url
                        if product_url is not None:
                            update_fields["product_url"] = product_url
                        if visibility is not None:
                            update_fields["visibility"] = visibility
                        if is_featured is not None:
                            update_fields["is_featured"] = is_featured
                        if priority is not None:
                            update_fields["priority"] = priority

                        changed_fields, old_values, new_values = self._collect_product_changes(
                            product=existing_product,
                            updates=update_fields,
                        )

                        for field, value in update_fields.items():
                            setattr(existing_product, field, value)
                        existing_product.last_stock_sync_at = stock_synced_at

                        if effective_attributes:
                            for key, value in effective_attributes.items():
                                pending_eav_rows.append((existing_product.id, key, value))

                        if changed_fields:
                            db.add(
                                ProductChange(
                                    upload_id=upload_record.id,
                                    product_id=existing_product.id,
                                    changed_fields=changed_fields,
                                    old_values=old_values,
                                    new_values=new_values,
                                )
                            )
                        pending_projection_products.append(existing_product)
                        stats["updated"] += 1
                    else:
                        new_product = Product(
                            sku=sku,
                            master_code=display_name,
                            group_id=group_id,
                            price=self._parse_float(row.get("price", 0)),
                            currency=(getattr(settings, "BASE_CURRENCY", "USD") or "USD").upper(),
                            description=row_desc,
                            image_url=image_url,
                            product_url=product_url,
                            object_id=object_id,
                            product_upload_id=upload_record.id,
                            search_text=search_text,
                            search_hash=search_hash,
                            stock_status=stock_status,
                            stock_qty=stock_qty,
                            last_stock_sync_at=stock_synced_at,
                            search_keywords=search_keywords,
                            attributes=attributes or {},
                            legacy_sku=legacy_skus,
                        )
                        if visibility is not None:
                            new_product.visibility = visibility
                        if is_featured is not None:
                            new_product.is_featured = is_featured
                        if priority is not None:
                            new_product.priority = priority
                        db.add(new_product)
                        if attributes:
                            pending_new_eav.append((new_product, attributes))
                        pending_projection_products.append(new_product)
                        stats["created"] += 1
                except Exception as row_error:
                    logger.error(f"Error importing row {row}: {row_error}")
                    stats["errors"] += 1

            if pending_new_eav:
                await db.flush()
                for product, attrs in pending_new_eav:
                    for key, value in attrs.items():
                        pending_eav_rows.append((product.id, key, value))

            if pending_eav_rows:
                metrics = await eav_service.bulk_upsert_product_attribute_rows(
                    db,
                    rows=pending_eav_rows,
                )
                logger.info(
                    "EAV import upsert: rows_total=%s unique_pairs=%s insert_rows=%s drop_empty=%s",
                    metrics.get("rows_total"),
                    metrics.get("unique_pairs"),
                    metrics.get("insert_rows"),
                    metrics.get("drop_empty"),
                )

            if pending_projection_products and bool(getattr(settings, "CHAT_PROJECTION_DUAL_WRITE_ENABLED", True)):
                projection_synced = await product_projection_sync_service.sync_products(
                    db,
                    products=pending_projection_products,
                )
                logger.info("Projection import sync rows=%s", projection_synced)

            await db.commit()

            # Schedule background embedding generation
            imported_count = stats["created"] + stats["updated"]
            if background_tasks and imported_count > 0:
                background_tasks.add_task(
                    self._generate_product_embeddings_background,
                    upload_id=upload_record.id,
                )

            await self._update_product_upload_status(
                db,
                upload_record.id,
                ProductUploadStatus.COMPLETED,
                imported_count=imported_count,
            )

            return {
                "message": "Product import initiated. Embeddings will be generated in background.",
                "stats": stats,
                "upload_id": upload_record.id,
                "status": ProductUploadStatus.COMPLETED,
            }

        except Exception as e:
            # Ensure the session is usable after flush/commit failures.
            try:
                await db.rollback()
            except Exception:
                pass
            await self._update_product_upload_status(
                db,
                upload_record.id,
                ProductUploadStatus.FAILED,
                error_message=str(e),
            )
            raise

    def _normalize_product_ids(self, product_ids: Optional[List[UUID]]) -> List[UUID]:
        if not product_ids:
            return []
        seen: set[UUID] = set()
        deduped: List[UUID] = []
        for product_id in product_ids:
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            deduped.append(product_id)
        return deduped

    def _embedding_candidate_filter(
        self,
        *,
        product_ids: List[UUID],
        upload_id: UUID | None,
    ):
        clauses = []

        if product_ids:
            clauses.append(Product.id.in_(product_ids))

        if upload_id:
            changed_in_upload = exists(
                select(1).where(
                    and_(
                        ProductChange.upload_id == upload_id,
                        ProductChange.product_id == Product.id,
                    )
                )
            )
            clauses.append(
                or_(
                    Product.product_upload_id == upload_id,
                    changed_in_upload,
                )
            )

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return or_(*clauses)

    async def _count_embedding_candidates(
        self,
        db: AsyncSession,
        *,
        product_ids: List[UUID],
        upload_id: UUID | None,
    ) -> int:
        candidate_filter = self._embedding_candidate_filter(
            product_ids=product_ids,
            upload_id=upload_id,
        )
        if candidate_filter is None:
            return 0

        subquery = (
            select(Product.id)
            .where(candidate_filter)
            .distinct()
            .subquery()
        )
        stmt = select(func.count()).select_from(subquery)
        result = await db.execute(stmt)
        return int(result.scalar() or 0)

    async def _fetch_embedding_candidate_page(
        self,
        db: AsyncSession,
        *,
        product_ids: List[UUID],
        upload_id: UUID | None,
        last_seen_id: UUID | None,
        page_size: int,
    ) -> List[Product]:
        candidate_filter = self._embedding_candidate_filter(
            product_ids=product_ids,
            upload_id=upload_id,
        )
        if candidate_filter is None:
            return []

        stmt = select(Product).where(candidate_filter)
        if last_seen_id is not None:
            stmt = stmt.where(Product.id > last_seen_id)
        stmt = stmt.order_by(Product.id).limit(page_size)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    def _is_embedding_payload_too_large(exc: Exception) -> bool:
        return is_embedding_payload_too_large(exc)

    def _is_transient_embedding_error(self, exc: Exception) -> bool:
        if self._is_embedding_payload_too_large(exc):
            return False
        return is_transient_embedding_error(exc)

    async def _generate_embeddings_with_retry(self, texts: List[str]) -> List[List[float]]:
        max_retries = max(0, int(getattr(settings, "PRODUCT_EMBEDDING_MAX_RETRIES", 4)))
        base_ms = max(1, int(getattr(settings, "PRODUCT_EMBEDDING_RETRY_BASE_MS", 500)))

        for attempt in range(max_retries + 1):
            try:
                return await llm_service.generate_embeddings_batch(texts)
            except Exception as exc:
                if attempt >= max_retries or not self._is_transient_embedding_error(exc):
                    raise
                jitter_ms = random.randint(0, base_ms)
                sleep_seconds = ((2**attempt) * base_ms + jitter_ms) / 1000.0
                logger.warning(
                    "Retrying embedding batch after transient error (attempt=%s/%s, size=%s): %s",
                    attempt + 1,
                    max_retries,
                    len(texts),
                    exc,
                )
                await asyncio.sleep(sleep_seconds)

        raise RuntimeError("Failed to generate embeddings after retries")

    async def _generate_embeddings_adaptive(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        try:
            return await self._generate_embeddings_with_retry(texts)
        except Exception as exc:
            if len(texts) <= 1 or not self._is_embedding_payload_too_large(exc):
                raise
            split_at = max(1, len(texts) // 2)
            left = await self._generate_embeddings_adaptive(texts[:split_at])
            right = await self._generate_embeddings_adaptive(texts[split_at:])
            return left + right

    async def _embed_payload_batch(
        self,
        *,
        semaphore: asyncio.Semaphore,
        payloads: List[Dict[str, Any]],
        vectors: List[Optional[List[float]]],
        start: int,
    ) -> None:
        texts = [payload["text"] for payload in payloads]
        async with semaphore:
            batch_vectors = await self._generate_embeddings_adaptive(texts)
        for offset, vector in enumerate(batch_vectors):
            vectors[start + offset] = vector

    async def _embed_product_payloads(self, payloads: List[Dict[str, Any]]) -> List[List[float]]:
        if not payloads:
            return []

        batch_size = max(1, int(getattr(settings, "PRODUCT_EMBEDDING_BATCH_SIZE", 128)))
        max_concurrency = max(1, int(getattr(settings, "PRODUCT_EMBEDDING_MAX_CONCURRENCY", 4)))
        semaphore = asyncio.Semaphore(max_concurrency)

        vectors: List[Optional[List[float]]] = [None] * len(payloads)
        tasks = []

        for start in range(0, len(payloads), batch_size):
            batch = payloads[start:start + batch_size]
            tasks.append(
                asyncio.create_task(
                    self._embed_payload_batch(
                        semaphore=semaphore,
                        payloads=batch,
                        vectors=vectors,
                        start=start,
                    )
                )
            )

        await asyncio.gather(*tasks)

        missing = [idx for idx, value in enumerate(vectors) if value is None]
        if missing:
            raise RuntimeError(f"Missing embedding vectors for payload indexes: {missing[:5]}")

        return [value for value in vectors if value is not None]

    async def _upsert_product_embeddings(
        self,
        db: AsyncSession,
        *,
        rows: List[Dict[str, Any]],
    ) -> None:
        if not rows:
            return

        stmt = pg_insert(ProductEmbedding).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProductEmbedding.product_id, ProductEmbedding.model],
            index_where=ProductEmbedding.model.isnot(None),
            set_={
                "embedding": stmt.excluded.embedding,
                "price_cache": stmt.excluded.price_cache,
                "category_id": stmt.excluded.category_id,
                "source_hash": stmt.excluded.source_hash,
            },
        )
        await db.execute(stmt)

    async def _process_product_embedding_page(
        self,
        db: AsyncSession,
        *,
        products: List[Product],
        model: str,
    ) -> Tuple[int, int]:
        if not products:
            return 0, 0

        product_ids = [product.id for product in products]
        existing_stmt = (
            select(ProductEmbedding)
            .where(ProductEmbedding.product_id.in_(product_ids))
            .where(ProductEmbedding.model == model)
        )
        existing_result = await db.execute(existing_stmt)
        existing_by_product: Dict[UUID, ProductEmbedding] = {}
        for embedding in existing_result.scalars().all():
            existing_by_product[embedding.product_id] = embedding

        payloads: List[Dict[str, Any]] = []
        skipped_unchanged = 0

        for product in products:
            text = product.search_text or f"{product.name} {product.description or ''} {product.sku}"
            source_hash = product.search_hash or self._hash_text(self._normalize_search_text(text))
            existing_embedding = existing_by_product.get(product.id)
            if existing_embedding and getattr(existing_embedding, "source_hash", None) == source_hash:
                skipped_unchanged += 1
                continue

            category_id = None
            if isinstance(product.attributes, dict):
                category_id = product.attributes.get("category")

            payloads.append(
                {
                    "product_id": product.id,
                    "text": text,
                    "price_cache": product.price,
                    "category_id": category_id,
                    "source_hash": source_hash,
                }
            )

        if not payloads:
            return 0, skipped_unchanged

        vectors = await self._embed_product_payloads(payloads)
        upsert_rows = []
        for payload, vector in zip(payloads, vectors):
            upsert_rows.append(
                {
                    "product_id": payload["product_id"],
                    "embedding": vector,
                    "price_cache": payload["price_cache"],
                    "model": model,
                    "category_id": payload["category_id"],
                    "source_hash": payload["source_hash"],
                }
            )

        await self._upsert_product_embeddings(db, rows=upsert_rows)
        await db.commit()
        return len(upsert_rows), skipped_unchanged

    async def _maybe_update_embedding_progress(
        self,
        db: AsyncSession,
        *,
        task_id: UUID,
        processed: int,
        total: int,
        last_progress: int,
        last_update_ts: float,
        interval_seconds: float,
    ) -> Tuple[int, float]:
        if total <= 0:
            return last_progress, last_update_ts

        progress = min(99, int((processed / total) * 100))
        now = time.monotonic()
        should_update = progress != last_progress or (now - last_update_ts) >= interval_seconds
        if not should_update:
            return last_progress, last_update_ts

        await task_service.update_task_status(db, task_id, TaskStatus.RUNNING, progress=progress)
        return progress, now

    async def _generate_product_embeddings_background(
        self,
        product_ids: List[UUID] | None = None,
        upload_id: UUID | None = None,
    ) -> None:
        """Background task to generate embeddings for products."""
        from app.db.session import AsyncSessionLocal

        normalized_ids = self._normalize_product_ids(product_ids)
        if not normalized_ids and not upload_id:
            logger.warning("Embedding task skipped: no product_ids or upload_id provided")
            return

        mode = "upload" if upload_id else "ids"
        description = (
            f"Generating embeddings for upload {upload_id}"
            if upload_id
            else f"Generating embeddings for {len(normalized_ids)} products"
        )
        metadata: Dict[str, Any] = {
            "mode": mode,
            "upload_id": str(upload_id) if upload_id else None,
            "product_count": len(normalized_ids),
        }

        async with AsyncSessionLocal() as db:
            task = await task_service.create_task(
                db,
                TaskType.EMBEDDING_GENERATION,
                description,
                metadata,
            )
            try:
                await task_service.update_task_status(db, task.id, TaskStatus.RUNNING, progress=0)

                total_candidates = await self._count_embedding_candidates(
                    db,
                    product_ids=normalized_ids,
                    upload_id=upload_id,
                )
                if total_candidates <= 0:
                    await task_service.update_task_status(db, task.id, TaskStatus.COMPLETED, progress=100)
                    return

                page_size = max(1, int(getattr(settings, "PRODUCT_EMBEDDING_PAGE_SIZE", 1000)))
                model = getattr(settings, "PRODUCT_EMBEDDING_MODEL", settings.EMBEDDING_MODEL)
                progress_interval = float(
                    max(1, int(getattr(settings, "PRODUCT_EMBEDDING_PROGRESS_INTERVAL_SECONDS", 5)))
                )

                processed = 0
                embedded = 0
                skipped = 0
                last_seen_id: UUID | None = None
                last_progress = -1
                last_progress_ts = 0.0

                while True:
                    page = await self._fetch_embedding_candidate_page(
                        db,
                        product_ids=normalized_ids,
                        upload_id=upload_id,
                        last_seen_id=last_seen_id,
                        page_size=page_size,
                    )
                    if not page:
                        break

                    last_seen_id = page[-1].id
                    updated_count, skipped_count = await self._process_product_embedding_page(
                        db,
                        products=page,
                        model=model,
                    )
                    embedded += updated_count
                    skipped += skipped_count
                    processed += len(page)

                    last_progress, last_progress_ts = await self._maybe_update_embedding_progress(
                        db,
                        task_id=task.id,
                        processed=processed,
                        total=total_candidates,
                        last_progress=last_progress,
                        last_update_ts=last_progress_ts,
                        interval_seconds=progress_interval,
                    )

                await task_service.update_task_status(db, task.id, TaskStatus.COMPLETED, progress=100)
                logger.info(
                    "Embedding task completed mode=%s total=%s embedded=%s skipped_unchanged=%s",
                    mode,
                    total_candidates,
                    embedded,
                    skipped,
                )
            except Exception as exc:
                logger.error(f"Error in background embedding generation: {exc}")
                await task_service.update_task_status(
                    db,
                    task.id,
                    TaskStatus.FAILED,
                    error_message=str(exc),
                )

    async def import_knowledge(
        self,
        db: AsyncSession,
        file: UploadFile,
        background_tasks: BackgroundTasks = None,
        uploaded_by: str | None = None
    ) -> Dict[str, int]:
        """
        Import knowledge articles from CSV files.
        """
        content = await file.read()
        filename = file.filename
        lower_filename = filename.lower()
        upload_session = await self._create_upload_session(
            db=db,
            content=content,
            filename=filename,
            content_type=file.content_type,
            uploaded_by=uploaded_by,
        )

        parsed_items: List[Dict[str, Any]] = [] # list of {title, full_text, chunks: [str], category, url}

        try:
            await self._update_upload_status(db, upload_session.id, KnowledgeUploadStatus.PROCESSING)
            # Parse file
            if lower_filename.endswith('.csv'):
                parsed_items = await self._parse_csv_knowledge(content)
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type. Use CSV.")
        except Exception as e:
            logger.error(f"Error parsing file {lower_filename}: {e}")
            await self._update_upload_status(db, upload_session.id, KnowledgeUploadStatus.FAILED, str(e))
            raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")
        
        # Create Data Structure (Article -> Version -> Chunks)
        stats = {"created": 0, "new_versions": 0, "errors": 0}
        articles_to_embed = []
        
        for item in parsed_items:
            try:
                # Check if exists
                stmt = select(KnowledgeArticle).where(KnowledgeArticle.title == item["title"])
                result = await db.execute(stmt)
                article = result.scalar_one_or_none()
                
                if not article:
                    # Create new
                    article = KnowledgeArticle(
                        title=item["title"],
                        content=item["full_text"], # Legacy field
                        category=item.get("category"),
                        url=item.get("url"),
                        upload_session_id=upload_session.id
                    )
                    db.add(article)
                    await db.commit()
                    await db.refresh(article)
                    stats["created"] += 1
                
                # Determine next version
                # Get max version
                stmt_v = select(func.max(KnowledgeArticleVersion.version)).where(KnowledgeArticleVersion.article_id == article.id)
                res_v = await db.execute(stmt_v)
                max_v = res_v.scalar() or 0
                new_v = max_v + 1
                
                # Create Version
                version = KnowledgeArticleVersion(
                    article_id=article.id,
                    version=new_v,
                    content_text=item["full_text"],
                    created_by=uploaded_by
                )
                db.add(version)
                article.active_version = new_v
                await db.commit() # Commit to get ID? ID is uuid, auto gen.
                stats["new_versions"] += 1
                
                # Create Chunks
                chunks_text = item["chunks"]
                for i, c_text in enumerate(chunks_text):
                    c_hash = self._hash_text(c_text)
                    chunk = KnowledgeChunk(
                        article_id=article.id,
                        version=new_v,
                        chunk_index=i,
                        chunk_text=c_text,
                        chunk_hash=c_hash
                    )
                    db.add(chunk)
                await db.commit()
                
                articles_to_embed.append(article.id)
                
            except Exception as e:
                logger.error(f"Error creating article/version: {e}")
                stats["errors"] += 1
        
        # Schedule background embedding generation
        # We pass the list of Article IDs. The BG task will look for chunks without embeddings.
        if background_tasks and articles_to_embed:
            background_tasks.add_task(
                self._generate_knowledge_embeddings_background,
                articles_to_embed,
                upload_session.id
            )
        else:
            await self._update_upload_status(db, upload_session.id, KnowledgeUploadStatus.COMPLETED)
        
        return {
            "stats": stats,
            "upload_id": upload_session.id,
            "status": KnowledgeUploadStatus.PROCESSING if articles_to_embed else KnowledgeUploadStatus.COMPLETED,
        }
    
    async def _parse_csv_knowledge(self, content: bytes) -> List[Dict[str, Any]]:
        return parse_csv_knowledge(content)
    
    def _chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        return chunk_text(text=text, chunk_size=chunk_size, overlap=overlap)
    
    def _hash_text(self, text: str) -> str:
        return hash_text(text)

    async def _generate_knowledge_embeddings_background(self, article_ids: List[UUID], upload_session_id: UUID | None = None) -> None:
        """
        Background task to generate embeddings for knowledge chunks.
        It finds chunks for the given articles that do NOT have embeddings yet (or specifically for the latest versions).
        Efficiently reuses embeddings by hash.
        """
        from app.db.session import AsyncSessionLocal
        
        async with AsyncSessionLocal() as db:
            try:
                # Create Task
                task = await task_service.create_task(
                    db,
                    TaskType.EMBEDDING_GENERATION,
                    f"Processing chunks for {len(article_ids)} articles",
                    {"article_ids": article_ids}
                )
                await task_service.update_task_status(db, task.id, TaskStatus.RUNNING)

                model = getattr(settings, "KNOWLEDGE_EMBEDDING_MODEL", settings.EMBEDDING_MODEL)

                # Find chunks for these articles that need embeddings
                # We simply select chunks and check their embedding relationship
                # Or for simplicity, select chunks created recently?
                # Best way: Select All Chunks for these articles. For each chunk, check if embedding exists.
                
                # Optimized: Select Chunks where not exists(Embedding)
                # But we just created them, so they likely don't have embeddings.
                
                stmt = (
                    select(KnowledgeChunk)
                    .join(KnowledgeEmbedding, KnowledgeChunk.id == KnowledgeEmbedding.chunk_id, isouter=True)
                    .where(
                        and_(
                            KnowledgeChunk.article_id.in_(article_ids),
                            KnowledgeEmbedding.id.is_(None)
                        )
                    )
                )
                
                result = await db.execute(stmt)
                chunks_to_process = result.scalars().all()
                
                total = len(chunks_to_process)
                processed = 0
                
                logger.info(f"Found {total} chunks to process")
                
                chunks_to_embed: List[KnowledgeChunk] = []

                for chunk in chunks_to_process:
                    # Check for REUSE
                    # Find ANY existing embedding with same chunk_hash
                    # We need to find a Chunk with same hash that DOES have an embedding
                    
                    reuse_stmt = (
                        select(KnowledgeEmbedding)
                        .join(KnowledgeChunk, KnowledgeEmbedding.chunk_id == KnowledgeChunk.id)
                        .where(KnowledgeChunk.chunk_hash == chunk.chunk_hash)
                        .where(or_(KnowledgeEmbedding.model.is_(None), KnowledgeEmbedding.model == model))
                        .limit(1)
                    )
                    reuse_res = await db.execute(reuse_stmt)
                    existing_emb = reuse_res.scalar_one_or_none()
                    
                    if existing_emb:
                        # Reuse
                        new_emb = KnowledgeEmbedding(
                            article_id=chunk.article_id,
                            chunk_id=chunk.id,
                            chunk_text=chunk.chunk_text,
                            embedding=existing_emb.embedding, # Copy vector
                            model=model,
                            version=chunk.version
                        )
                        db.add(new_emb)
                        processed += 1
                    else:
                        chunks_to_embed.append(chunk)

                if processed:
                    await db.commit()
                    progress = int(processed / total * 100)
                    await task_service.update_task_status(db, task.id, TaskStatus.RUNNING, progress=progress)

                # Batch embed remaining chunks
                batch_size = 50
                for start in range(0, len(chunks_to_embed), batch_size):
                    batch = chunks_to_embed[start:start + batch_size]
                    vectors = await llm_service.generate_embeddings_batch([c.chunk_text for c in batch])
                    for chunk, vector in zip(batch, vectors):
                        new_emb = KnowledgeEmbedding(
                            article_id=chunk.article_id,
                            chunk_id=chunk.id,
                            chunk_text=chunk.chunk_text,
                            embedding=vector,
                            model=model,
                            version=chunk.version
                        )
                        db.add(new_emb)
                    processed += len(batch)
                    await db.commit()
                    progress = int(processed / total * 100)
                    await task_service.update_task_status(db, task.id, TaskStatus.RUNNING, progress=progress)

                await task_service.update_task_status(db, task.id, TaskStatus.COMPLETED, progress=100)
                
                if upload_session_id:
                    await self._update_upload_status(db, upload_session_id, KnowledgeUploadStatus.COMPLETED)
                
            except Exception as e:
                logger.error(f"Error in background chunk embedding: {e}")
                if upload_session_id:
                    await self._update_upload_status(db, upload_session_id, KnowledgeUploadStatus.FAILED, str(e))

    async def _create_upload_session(
        self,
        db: AsyncSession,
        content: bytes,
        filename: str,
        content_type: str | None,
        uploaded_by: str | None = None
    ) -> KnowledgeUpload:
        """Persist the raw file to disk and create an upload session record."""
        upload_id = uuid4()
        upload_root = Path(settings.UPLOAD_DIR)
        upload_root.mkdir(parents=True, exist_ok=True)
        file_path = knowledge_upload_storage_path(upload_root, upload_id, filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

        session = KnowledgeUpload(
            id=upload_id,
            filename=filename,
            content_type=content_type,
            file_size=len(content),
            file_path=str(file_path),
            uploaded_by=uploaded_by,
            status=KnowledgeUploadStatus.PENDING,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def _update_upload_status(
        self,
        db: AsyncSession,
        upload_id: UUID,
        status: KnowledgeUploadStatus,
        error_message: str | None = None
    ) -> None:
        """Update upload session status with optional error message."""
        stmt = select(KnowledgeUpload).where(KnowledgeUpload.id == upload_id)
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if not session:
            return

        session.status = status
        session.error_message = error_message
        if status == KnowledgeUploadStatus.COMPLETED:
            session.completed_at = datetime.utcnow()
        session.updated_at = datetime.utcnow()
        await db.commit()
    
    async def _create_product_upload(
        self,
        db: AsyncSession,
        content: bytes,
        filename: str,
        content_type: str | None,
        uploaded_by: str | None = None,
    ) -> ProductUpload:
        upload_id = uuid4()
        storage_path = self._product_upload_storage_path(upload_id, filename)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)

        upload_by_uuid = None
        if uploaded_by:
            try:
                upload_by_uuid = UUID(uploaded_by)
            except ValueError:
                upload_by_uuid = None

        record = ProductUpload(
            id=upload_id,
            filename=filename,
            content_type=content_type,
            file_size=len(content),
            uploaded_by=upload_by_uuid,
            status=ProductUploadStatus.PENDING,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record

    async def _update_product_upload_status(
        self,
        db: AsyncSession,
        upload_id: UUID,
        status: ProductUploadStatus,
        imported_count: int | None = None,
        error_message: str | None = None,
    ) -> None:
        stmt = select(ProductUpload).where(ProductUpload.id == upload_id)
        result = await db.execute(stmt)
        upload = result.scalar_one_or_none()
        if not upload:
            return

        upload.status = status
        upload.error_message = error_message
        if imported_count is not None:
            upload.imported_products = imported_count
        if status == ProductUploadStatus.COMPLETED:
            upload.completed_at = datetime.utcnow()
        upload.updated_at = datetime.utcnow()
        await db.commit()

    async def list_product_uploads(
        self, db: AsyncSession, page: int, page_size: int
    ) -> Tuple[List[ProductUpload], int]:
        offset = (page - 1) * page_size
        count_stmt = select(func.count()).select_from(ProductUpload)
        total = int((await db.execute(count_stmt)).scalar() or 0)

        stmt = (
            select(ProductUpload)
            .order_by(ProductUpload.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        return result.scalars().all(), total

    async def get_product_upload(self, db: AsyncSession, upload_id: UUID) -> ProductUpload | None:
        stmt = select(ProductUpload).where(ProductUpload.id == upload_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    def _product_upload_storage_path(self, upload_id: UUID, filename: str) -> Path:
        return product_upload_storage_path(Path(settings.UPLOAD_DIR), upload_id, filename)

    async def get_product_upload_file_path(self, db: AsyncSession, upload_id: UUID) -> Path:
        upload = await self.get_product_upload(db, upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        file_path = self._product_upload_storage_path(upload.id, upload.filename)
        try:
            safe_path = ensure_product_upload_path_in_root(Path(settings.UPLOAD_DIR), file_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not safe_path.exists():
            raise HTTPException(status_code=404, detail="Stored file is missing")
        return safe_path

    async def delete_product_upload(self, db: AsyncSession, upload_id: UUID) -> None:
        upload = await self.get_product_upload(db, upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        stmt = select(Product).where(Product.product_upload_id == upload_id)
        result = await db.execute(stmt)
        for product in result.scalars().all():
            product.product_upload_id = None

        storage_path = self._product_upload_storage_path(upload.id, upload.filename)
        try:
            safe_storage_path = ensure_product_upload_path_in_root(Path(settings.UPLOAD_DIR), storage_path)
        except ValueError:
            safe_storage_path = None
        if safe_storage_path and safe_storage_path.exists():
            try:
                safe_storage_path.unlink()
                storage_dir = safe_storage_path.parent
                if storage_dir.exists():
                    storage_dir.rmdir()
            except OSError:
                pass

        await db.delete(upload)
        await db.commit()

    async def list_knowledge_uploads(
        self, db: AsyncSession, page: int, page_size: int
    ) -> Tuple[List[KnowledgeUpload], int]:
        offset = (page - 1) * page_size
        count_stmt = select(func.count()).select_from(KnowledgeUpload)
        total = int((await db.execute(count_stmt)).scalar() or 0)

        stmt = (
            select(KnowledgeUpload)
            .options(selectinload(KnowledgeUpload.articles))
            .order_by(KnowledgeUpload.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        return result.scalars().unique().all(), total

    async def get_upload(self, db: AsyncSession, upload_id: UUID) -> KnowledgeUpload | None:
        stmt = (
            select(KnowledgeUpload)
            .options(selectinload(KnowledgeUpload.articles))
            .where(KnowledgeUpload.id == upload_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_upload_file_path(self, db: AsyncSession, upload_id: UUID) -> Path:
        upload = await self.get_upload(db, upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        file_path = Path(upload.file_path)
        try:
            safe_path = ensure_knowledge_upload_path_in_root(Path(settings.UPLOAD_DIR), file_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not safe_path.exists():
            raise HTTPException(status_code=404, detail="Stored file is missing")
        return safe_path

    async def delete_knowledge_upload(self, db: AsyncSession, upload_id: UUID) -> None:
        stmt = select(KnowledgeUpload).where(KnowledgeUpload.id == upload_id)
        result = await db.execute(stmt)
        upload = result.scalar_one_or_none()
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        await db.execute(
            update(KnowledgeArticle)
            .where(KnowledgeArticle.upload_session_id == upload_id)
            .values(upload_session_id=None)
        )

        # Remove stored file safely
        file_path = Path(upload.file_path)
        try:
            safe_path = ensure_knowledge_upload_path_in_root(Path(settings.UPLOAD_DIR), file_path)
        except ValueError:
            safe_path = None

        if safe_path is not None:
            safe_path.unlink(missing_ok=True)
            try:
                safe_path.parent.rmdir()
            except OSError:
                pass

        await db.execute(delete(KnowledgeUpload).where(KnowledgeUpload.id == upload_id))
        await db.commit()

data_import_service = DataImportService()
