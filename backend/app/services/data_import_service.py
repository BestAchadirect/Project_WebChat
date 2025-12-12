import csv
import io
import codecs
from typing import List, Dict, Any, Generator
from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.product import Product, ProductEmbedding
from app.models.knowledge import KnowledgeArticle, KnowledgeEmbedding
from app.services.llm_service import llm_service

class DataImportService:
    @staticmethod
    def get_product_template() -> str:
        """Returns the CSV header for products."""
        return "sku,name,price,description,category,image_url,product_url,object_id,attributes_json"

    @staticmethod
    def get_knowledge_template() -> str:
        """Returns the CSV header for knowledge articles."""
        return "title,content,category,url"
        
    async def import_products(self, db: AsyncSession, file: UploadFile) -> Dict[str, int]:
        content = await file.read()
        # Decode bytes to string
        text_content = content.decode("utf-8-sig") # Handle BOM
        
        csv_reader = csv.DictReader(io.StringIO(text_content))
        
        stats = {"created": 0, "updated": 0, "errors": 0}
        products_to_embed = []
        
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
                    # Update (Simplified for now, just updating fields)
                    existing_product.name = row["name"]
                    existing_product.price = float(row.get("price", 0))
                    existing_product.description = row.get("description", "")
                    # ... map other fields
                    stats["updated"] += 1
                    products_to_embed.append(existing_product)
                else:
                    # Create
                    new_product = Product(
                        sku=sku,
                        name=row["name"],
                        price=float(row.get("price", 0)),
                        description=row.get("description", ""),
                        image_url=row.get("image_url"),
                        product_url=row.get("product_url"),
                        object_id=row.get("object_id"),
                        # attributes handling would go here (json parse)
                    )
                    db.add(new_product)
                    stats["created"] += 1
                    products_to_embed.append(new_product)
            except Exception as e:
                print(f"Error importing row {row}: {e}")
                stats["errors"] += 1
        
        await db.commit()
        
        # Process Embeddings for all processed products
        # In production this should be batched or backgrounded
        for product in products_to_embed:
            await self._update_product_embedding(db, product)
            
        return stats

    async def import_knowledge(self, db: AsyncSession, file: UploadFile) -> Dict[str, int]:
        content = await file.read()
        text_content = content.decode("utf-8-sig")
        csv_reader = csv.DictReader(io.StringIO(text_content))
        
        stats = {"created": 0, "errors": 0}
        
        for row in csv_reader:
            try:
                if not row.get("title") or not row.get("content"):
                    continue
                    
                article = KnowledgeArticle(
                    title=row["title"],
                    content=row["content"],
                    category=row.get("category"),
                    url=row.get("url")
                )
                db.add(article)
                await db.commit()
                await db.refresh(article)
                
                # Create Embedding
                await self._create_knowledge_embedding(db, article)
                stats["created"] += 1
                
            except Exception as e:
                print(f"Error importing knowledge row: {e}")
                stats["errors"] += 1
                
        return stats

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

data_import_service = DataImportService()
