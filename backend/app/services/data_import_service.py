import csv
import io
from pathlib import Path
from typing import List, Dict, Any
from uuid import uuid4, UUID
from datetime import datetime
from fastapi import UploadFile, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import PyPDF2
from docx import Document as DocxDocument

from app.models.product import Product, ProductEmbedding
from app.models.knowledge import (
    KnowledgeArticle,
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
    def get_product_template() -> str:
        """Returns the CSV header for products."""
        return "sku,name,price,description,category,image_url,product_url,object_id,attributes_json"

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
            for row in csv_reader:
                try:
                    # Basic Validation
                    if not row.get("sku") or not row.get("name"):
                        continue

                    sku = row["sku"].strip()

                    # Check exist
                    stmt = select(Product).where(Product.sku == sku)
                    result = await db.execute(stmt)
                    existing_product = result.scalar_one_or_none()

                    if existing_product:
                        existing_product.name = row["name"]
                        existing_product.price = float(row.get("price", 0))
                        existing_product.description = row.get("description", "")
                        stats["updated"] += 1
                        products_to_embed.append(existing_product)
                    else:
                        new_product = Product(
                            sku=sku,
                            name=row["name"],
                            price=float(row.get("price", 0)),
                            description=row.get("description", ""),
                            image_url=row.get("image_url"),
                            product_url=row.get("product_url"),
                            object_id=row.get("object_id"),
                        )
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
            await self._update_product_upload_status(
                db,
                upload_record.id,
                ProductUploadStatus.FAILED,
                error_message=str(e),
            )
            raise

    async def _generate_product_embeddings_background(self, product_ids: List[int]) -> None:
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
                print(f"Error in background embedding generation: {e}")
                # Task status update would happen here if we had task_id

    async def import_knowledge(
        self,
        db: AsyncSession,
        file: UploadFile,
        background_tasks: BackgroundTasks = None,
        uploaded_by: str | None = None
    ) -> Dict[str, int]:
        """
        Import knowledge articles from CSV, PDF, or DOCX files.
        Supports multiple file formats for flexible knowledge base population.
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

        articles_to_create: List[Dict[str, Any]] = []

        try:
            await self._update_upload_status(db, upload_session.id, KnowledgeUploadStatus.PROCESSING)
            # Parse file based on extension
            if lower_filename.endswith('.csv'):
                articles_to_create = await self._parse_csv_knowledge(content)
            elif lower_filename.endswith('.pdf'):
                articles_to_create = await self._parse_pdf_knowledge(content, lower_filename)
            elif lower_filename.endswith('.docx'):
                articles_to_create = await self._parse_docx_knowledge(content, lower_filename)
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type. Use CSV, PDF, or DOCX.")
        except Exception as e:
            logger.error(f"Error parsing file {lower_filename}: {e}")
            await self._update_upload_status(db, upload_session.id, KnowledgeUploadStatus.FAILED, str(e))
            raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")
        
        # Create articles and schedule embeddings
        stats = {"created": 0, "errors": 0}
        articles_to_embed = []
        
        for article_data in articles_to_create:
            try:
                article = KnowledgeArticle(**article_data, upload_session_id=upload_session.id)
                db.add(article)
                await db.commit()
                await db.refresh(article)
                stats["created"] += 1
                articles_to_embed.append(article)
            except Exception as e:
                logger.error(f"Error creating article: {e}")
                stats["errors"] += 1
        
        # Schedule background embedding generation
        if background_tasks and articles_to_embed:
            background_tasks.add_task(
                self._generate_knowledge_embeddings_background,
                [a.id for a in articles_to_embed],
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
        """Parse CSV file for knowledge articles."""
        text_content = content.decode("utf-8-sig")
        csv_reader = csv.DictReader(io.StringIO(text_content))
        
        articles = []
        for row in csv_reader:
            if row.get("title") and row.get("content"):
                articles.append({
                    "title": row["title"].strip(),
                    "content": row["content"].strip(),
                    "category": row.get("category", "general").strip(),
                    "url": row.get("url", "").strip() or None
                })
        
        return articles
    
    async def _parse_pdf_knowledge(self, content: bytes, filename: str) -> List[Dict[str, Any]]:
        """Parse PDF file for knowledge articles."""
        pdf_file = io.BytesIO(content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        
        articles = []
        full_text = ""
        
        for page_num, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"
        
        # Chunk the text into manageable pieces
        chunks = self._chunk_text(full_text, chunk_size=2000, overlap=200)
        
        for idx, chunk in enumerate(chunks):
            if chunk.strip():
                articles.append({
                    "title": f"{filename} - Section {idx + 1}",
                    "content": chunk.strip(),
                    "category": "pdf_document",
                    "url": None
                })
        
        return articles
    
    async def _parse_docx_knowledge(self, content: bytes, filename: str) -> List[Dict[str, Any]]:
        """Parse DOCX file for knowledge articles."""
        docx_file = io.BytesIO(content)
        doc = DocxDocument(docx_file)
        
        articles = []
        full_text = ""
        
        for para in doc.paragraphs:
            if para.text.strip():
                full_text += para.text + "\n"
        
        # Chunk the text into manageable pieces
        chunks = self._chunk_text(full_text, chunk_size=2000, overlap=200)
        
        for idx, chunk in enumerate(chunks):
            if chunk.strip():
                articles.append({
                    "title": f"{filename} - Section {idx + 1}",
                    "content": chunk.strip(),
                    "category": "docx_document",
                    "url": None
                })
        
        return articles
    
    def _chunk_text(self, text: str, chunk_size: int = 2000, overlap: int = 200) -> List[str]:
        """Split text into overlapping chunks."""
        chunks = []
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start += chunk_size - overlap
        
        return chunks
    
    async def _generate_knowledge_embeddings_background(self, article_ids: List[UUID], upload_session_id: UUID | None = None) -> None:
        """Background task to generate embeddings for knowledge articles."""
        from app.db.session import AsyncSessionLocal
        
        async with AsyncSessionLocal() as db:
            try:
                # Create task
                task = await task_service.create_task(
                    db,
                    TaskType.EMBEDDING_GENERATION,
                    f"Generating embeddings for {len(article_ids)} knowledge articles",
                    {"article_ids": article_ids}
                )
                
                await task_service.update_task_status(db, task.id, TaskStatus.RUNNING)
                
                # Get articles
                stmt = select(KnowledgeArticle).where(KnowledgeArticle.id.in_(article_ids))
                result = await db.execute(stmt)
                articles = result.scalars().all()
                
                total = len(articles)
                for idx, article in enumerate(articles):
                    await self._create_knowledge_embedding(db, article)
                    progress = int((idx + 1) / total * 100)
                    await task_service.update_task_status(db, task.id, TaskStatus.RUNNING, progress=progress)
                
                await task_service.update_task_status(db, task.id, TaskStatus.COMPLETED, progress=100)
                logger.info(f"Completed embedding generation for {len(articles)} knowledge articles")
                if upload_session_id:
                    await self._update_upload_status(db, upload_session_id, KnowledgeUploadStatus.COMPLETED)
                
            except Exception as e:
                logger.error(f"Error in background embedding generation: {e}")
                if upload_session_id:
                    await self._update_upload_status(db, upload_session_id, KnowledgeUploadStatus.FAILED, str(e))

    async def _update_product_embedding(self, db: AsyncSession, product: Product):
        # Generate text representation
        text = f"{product.name} {product.description or ''} {product.sku}"
        embedding_vector = await llm_service.generate_embedding(text)
        
        # Check if exists
        # Simplified: Delete old, add new
        # In real app: check if exists
        
        emb = ProductEmbedding(
            product_id=product.id,
            embedding=embedding_vector,
            price_cache=product.price
            # category_id ...
        )
        db.add(emb)
        await db.commit()

    async def _create_knowledge_embedding(self, db: AsyncSession, article: KnowledgeArticle):
        embedding_vector = await llm_service.generate_embedding(article.content) # Full content or chunk?
        # Assuming simple 1-1 for now, or use chunking service
        
        emb = KnowledgeEmbedding(
            article_id=article.id,
            embedding=embedding_vector,
            chunk_text=article.content[:1000] # Store snippet
        )
        db.add(emb)
        await db.commit()

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
        safe_name = Path(filename).name  # prevent path traversal from filename
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
        """Store a product upload file and create a tracking record."""
        upload_id = uuid4()
        upload_root = Path(settings.UPLOAD_DIR) / "product_uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        upload_dir = upload_root / str(upload_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        file_path = upload_dir / safe_name
        file_path.write_bytes(content)

        record = ProductUpload(
            id=upload_id,
            filename=filename,
            content_type=content_type,
            file_size=len(content),
            file_path=str(file_path),
            uploaded_by=uploaded_by,
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

    async def get_product_upload_file_path(self, db: AsyncSession, upload_id: UUID) -> Path:
        upload = await self.get_product_upload(db, upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        file_path = Path(upload.file_path)
        upload_root = (Path(settings.UPLOAD_DIR) / "product_uploads").resolve()
        resolved = file_path.resolve()
        if upload_root not in resolved.parents:
            raise HTTPException(status_code=400, detail="Invalid file path")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Stored file is missing")
        return file_path

    async def delete_product_upload(self, db: AsyncSession, upload_id: UUID) -> None:
        upload = await self.get_product_upload(db, upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        file_path = Path(upload.file_path)
        upload_root = (Path(settings.UPLOAD_DIR) / "product_uploads").resolve()
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

    async def list_knowledge_uploads(self, db: AsyncSession) -> List[KnowledgeUpload]:
        """Return recent knowledge uploads with article counts eager loaded."""
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
        """Return safe path to stored upload, raising if missing."""
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
        """Delete a knowledge upload and all associated data."""
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
