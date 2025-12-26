import csv
import io
import json
import html
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Tuple
from uuid import uuid4, UUID
from datetime import datetime
from fastapi import UploadFile, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.models.product import Product, ProductEmbedding
from app.models.knowledge import (
    KnowledgeArticle,
    KnowledgeArticleVersion,
    KnowledgeChunk,
    KnowledgeEmbedding,
    KnowledgeUpload,
    KnowledgeUploadStatus,
)
from app.models.product_upload import ProductUpload, ProductUploadStatus
from app.services.llm_service import llm_service
from app.services.task_service import task_service
from app.models.task import TaskType, TaskStatus
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)

class DataImportService:
    @staticmethod
    def _parse_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return None
            try:
                return int(float(v))
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_float(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return 0.0
            try:
                return float(v)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _normalize_search_text(text: str) -> str:
        if not text:
            return ""
        t = html.unescape(text)
        t = t.lower()
        t = re.sub(r"\s+", " ", t).strip()
        return t

    @staticmethod
    def get_product_template() -> str:
        """Returns the CSV header for products."""
        # master_code allows grouping multiple SKUs. stock_status can be 'in_stock' or 'out_of_stock'.
        return (
            "sku,master_code,name,price,stock_status,description,category,image_url,product_url,object_id,attributes_json,"
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
        products_to_embed = []

        try:
            await self._update_product_upload_status(db, upload_record.id, ProductUploadStatus.PROCESSING)
            for row in csv_reader:
                try:
                    # Basic Validation
                    if not row.get("sku") or not row.get("name"):
                        continue

                    sku = row["sku"].strip()
                    row_desc = row.get("description", "")
                    row_name = row["name"]

                    object_id_raw = row.get("object_id")
                    object_id = (object_id_raw.strip() if isinstance(object_id_raw, str) else object_id_raw) or None
                    
                    master_code_raw = row.get("master_code")
                    master_code = (master_code_raw.strip() if isinstance(master_code_raw, str) else master_code_raw) or None

                    stock_status_raw = row.get("stock_status", "in_stock").lower().strip()
                    stock_status = "in_stock" if stock_status_raw in ["in_stock", "1", "true", "yes"] else "out_of_stock"
                    
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

                    attribute_columns = [
                        "jewelry_type",
                        "material",
                        "length",
                        "size",
                        "cz_color",
                        "design",
                        "crystal_color",
                        "color",
                        "gauge",
                        "size_in_pack",
                        "rack",
                        "height",
                        "packing_option",
                        "pincher_size",
                        "ring_size",
                        "quantity_in_bulk",
                        "opal_color",
                        "threading",
                        "outer_diameter",
                        "pearl_color",
                    ]
                    for key in attribute_columns:
                        val = row.get(key)
                        if val is None:
                            continue
                        if isinstance(val, str):
                            val = val.strip()
                            if not val:
                                continue
                        if key in {"size_in_pack", "quantity_in_bulk"}:
                            parsed_int = self._parse_int(val)
                            if parsed_int is not None:
                                attributes[key] = parsed_int
                        else:
                            attributes[key] = val

                    category_raw = row.get("category")
                    category = category_raw.strip() if isinstance(category_raw, str) else category_raw
                    if isinstance(category, str) and category.strip():
                        attributes["category"] = category.strip()

                    # Compute search values
                    search_parts = [
                        str(row_name or ""),
                        str(row_desc or ""),
                        str(sku or ""),
                        str(attributes.get("jewelry_type") or ""),
                        str(attributes.get("material") or ""),
                        str(attributes.get("gauge") or ""),
                        str(attributes.get("color") or ""),
                        str(attributes.get("threading") or ""),
                        str(attributes.get("outer_diameter") or ""),
                        str(attributes.get("length") or ""),
                        str(attributes.get("size") or ""),
                        str(attributes.get("design") or ""),
                        str(attributes.get("crystal_color") or ""),
                        str(attributes.get("cz_color") or ""),
                        str(attributes.get("opal_color") or ""),
                        str(attributes.get("pearl_color") or ""),
                    ]
                    search_text = self._normalize_search_text(" ".join([p for p in search_parts if p]))
                    search_hash = self._hash_text(search_text)

                    # Check exist
                    stmt = select(Product).where(Product.sku == sku)
                    result = await db.execute(stmt)
                    existing_product = result.scalar_one_or_none()

                    if existing_product:
                        existing_product.name = row_name
                        existing_product.price = self._parse_float(row.get("price", 0))
                        existing_product.currency = (getattr(settings, "BASE_CURRENCY", "USD") or "USD").upper()
                        existing_product.description = row_desc
                        existing_product.product_upload_id = upload_record.id
                        existing_product.search_text = search_text
                        existing_product.search_hash = search_hash
                        existing_product.attributes = attributes or (existing_product.attributes or {})
                        existing_product.object_id = object_id
                        existing_product.master_code = master_code
                        existing_product.stock_status = stock_status

                        # Mirror common attributes into dedicated columns (if present in DB)
                        for k in attribute_columns:
                            if k in {"size_in_pack", "quantity_in_bulk"}:
                                setattr(existing_product, k, self._parse_int(attributes.get(k)))
                            else:
                                setattr(existing_product, k, attributes.get(k))
                        
                        stats["updated"] += 1
                        products_to_embed.append(existing_product)
                    else:
                        new_product = Product(
                            sku=sku,
                            name=row_name,
                            price=self._parse_float(row.get("price", 0)),
                            currency=(getattr(settings, "BASE_CURRENCY", "USD") or "USD").upper(),
                            description=row_desc,
                            image_url=row.get("image_url"),
                            product_url=row.get("product_url"),
                            object_id=object_id,
                            product_upload_id=upload_record.id,
                            search_text=search_text,
                            search_hash=search_hash,
                            master_code=master_code,
                            stock_status=stock_status,
                            attributes=attributes or {},
                        )
                        for k in attribute_columns:
                            if k in {"size_in_pack", "quantity_in_bulk"}:
                                setattr(new_product, k, self._parse_int(attributes.get(k)))
                            else:
                                setattr(new_product, k, attributes.get(k))
                        db.add(new_product)
                        stats["created"] += 1
                        products_to_embed.append(new_product)
                except Exception as row_error:
                    logger.error(f"Error importing row {row}: {row_error}")
                    stats["errors"] += 1

            await db.commit()

            # Schedule background embedding generation
            if background_tasks and products_to_embed:
                background_tasks.add_task(
                    self._generate_product_embeddings_background,
                    [p.id for p in products_to_embed],
                )

            await self._update_product_upload_status(
                db,
                upload_record.id,
                ProductUploadStatus.COMPLETED,
                imported_count=stats["created"] + stats["updated"],
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

    async def _generate_product_embeddings_background(self, product_ids: List[UUID]) -> None:
        """Background task to generate embeddings for products."""
        from app.db.session import AsyncSessionLocal
        
        async with AsyncSessionLocal() as db:
            try:
                # Create task
                task = await task_service.create_task(
                    db,
                    TaskType.EMBEDDING_GENERATION,
                    f"Generating embeddings for {len(product_ids)} products",
                    {"product_ids": product_ids}
                )
                
                await task_service.update_task_status(db, task.id, TaskStatus.RUNNING)
                
                # Get products
                stmt = select(Product).where(Product.id.in_(product_ids))
                result = await db.execute(stmt)
                products = result.scalars().all()
                
                total = len(products)
                for idx, product in enumerate(products):
                    await self._update_product_embedding(db, product)
                    progress = int((idx + 1) / total * 100)
                    await task_service.update_task_status(db, task.id, TaskStatus.RUNNING, progress=progress)
                
                await task_service.update_task_status(db, task.id, TaskStatus.COMPLETED, progress=100)
                
            except Exception as e:
                logger.error(f"Error in background embedding generation: {e}")

    async def _update_product_embedding(self, db: AsyncSession, product: Product):
        # Check if embedding exists and hash matches
        # For simplicity, we regenerate if calling this function. 
        # But we can optimize using search_hash in future.
        
        model = settings.EMBEDDING_MODEL
        text = product.search_text or f"{product.name} {product.description or ''} {product.sku}"
        source_hash = product.search_hash or self._hash_text(self._normalize_search_text(text))

        stmt = select(ProductEmbedding).where(
            and_(
                ProductEmbedding.product_id == product.id,
                ProductEmbedding.model == model,
            )
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing and getattr(existing, "source_hash", None) == source_hash:
            return

        embedding_vector = await llm_service.generate_embedding(text)

        category_id = None
        if isinstance(product.attributes, dict):
            category_id = product.attributes.get("category")

        if existing:
            existing.embedding = embedding_vector
            existing.price_cache = product.price
            existing.category_id = category_id
            existing.source_hash = source_hash
            db.add(existing)
        else:
            emb = ProductEmbedding(
                product_id=product.id,
                embedding=embedding_vector,
                price_cache=product.price,
                model=model,
                category_id=category_id,
                source_hash=source_hash,
            )
            db.add(emb)

        await db.commit()

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
        text_content = content.decode("utf-8-sig")
        csv_reader = csv.DictReader(io.StringIO(text_content))
        items = []
        for row in csv_reader:
            if row.get("title") and row.get("content"):
                full_text = row["content"].strip()
                chunks = self._chunk_text(full_text)
                items.append({
                    "title": row["title"].strip(),
                    "full_text": full_text,
                    "chunks": chunks,
                    "category": row.get("category", "general").strip(),
                    "url": row.get("url", "").strip() or None
                })
        return items
    
    def _chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        # Reduced chunk size default for granular embeddings
        chunks = []
        start = 0
        text_len = len(text)
        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start += chunk_size - overlap
        return chunks
    
    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

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
                
                for chunk in chunks_to_process:
                    # Check for REUSE
                    # Find ANY existing embedding with same chunk_hash
                    # We need to find a Chunk with same hash that DOES have an embedding
                    
                    reuse_stmt = (
                        select(KnowledgeEmbedding)
                        .join(KnowledgeChunk, KnowledgeEmbedding.chunk_id == KnowledgeChunk.id)
                        .where(KnowledgeChunk.chunk_hash == chunk.chunk_hash)
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
                            model=existing_emb.model,
                            version=chunk.version
                        )
                        db.add(new_emb)
                    else:
                        # Generate
                        vector = await llm_service.generate_embedding(chunk.chunk_text)
                        new_emb = KnowledgeEmbedding(
                            article_id=chunk.article_id,
                            chunk_id=chunk.id,
                            chunk_text=chunk.chunk_text,
                            embedding=vector,
                            model="text-embedding-3-small", 
                            version=chunk.version
                        )
                        db.add(new_emb)
                    
                    processed += 1
                    if processed % 10 == 0:
                        await db.commit() # Commit periodically
                        progress = int(processed / total * 100)
                        await task_service.update_task_status(db, task.id, TaskStatus.RUNNING, progress=progress)

                await db.commit()
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
        upload_dir = upload_root / str(upload_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        file_path = upload_dir / safe_name
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

    async def list_product_uploads(self, db: AsyncSession) -> List[ProductUpload]:
        stmt = select(ProductUpload).order_by(ProductUpload.created_at.desc())
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_product_upload(self, db: AsyncSession, upload_id: UUID) -> ProductUpload | None:
        stmt = select(ProductUpload).where(ProductUpload.id == upload_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    def _product_upload_storage_path(self, upload_id: UUID, filename: str) -> Path:
        upload_root = Path(settings.UPLOAD_DIR) / "product_uploads"
        return upload_root / str(upload_id) / Path(filename).name

    async def get_product_upload_file_path(self, db: AsyncSession, upload_id: UUID) -> Path:
        upload = await self.get_product_upload(db, upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        file_path = self._product_upload_storage_path(upload.id, upload.filename)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Stored file is missing")
        return file_path

    async def delete_product_upload(self, db: AsyncSession, upload_id: UUID) -> None:
        upload = await self.get_product_upload(db, upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        stmt = select(Product).where(Product.product_upload_id == upload_id)
        result = await db.execute(stmt)
        for product in result.scalars().all():
            product.product_upload_id = None

        storage_path = self._product_upload_storage_path(upload.id, upload.filename)
        if storage_path.exists():
            try:
                storage_path.unlink()
                storage_dir = storage_path.parent
                if storage_dir.exists():
                    storage_dir.rmdir()
            except OSError:
                pass

        await db.delete(upload)
        await db.commit()

    async def list_knowledge_uploads(self, db: AsyncSession) -> List[KnowledgeUpload]:
        stmt = (
            select(KnowledgeUpload)
            .options(selectinload(KnowledgeUpload.articles))
            .order_by(KnowledgeUpload.created_at.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().unique().all()

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
        upload_root = Path(settings.UPLOAD_DIR).resolve()
        resolved = file_path.resolve()
        if upload_root not in resolved.parents:
            raise HTTPException(status_code=400, detail="Invalid file path")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Stored file is missing")
        return file_path

    async def delete_knowledge_upload(self, db: AsyncSession, upload_id: UUID) -> None:
        upload = await self.get_upload(db, upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        # Remove stored file safely
        file_path = Path(upload.file_path)
        upload_root = Path(settings.UPLOAD_DIR).resolve()
        try:
            resolved = file_path.resolve()
        except FileNotFoundError:
            resolved = file_path

        if upload_root in resolved.parents or resolved == upload_root:
            file_path.unlink(missing_ok=True)
            try:
                file_path.parent.rmdir()
            except OSError:
                pass

        await db.delete(upload)
        await db.commit()

data_import_service = DataImportService()
